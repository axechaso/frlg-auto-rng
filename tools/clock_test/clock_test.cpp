// FRLG diagnostic only. No serial, capture, input, calibration or logging.
// EonTimer clock/phase-runner design: perf_counter (Windows QPC), absolute
// elapsed time and a 2 ms non-sleeping tail. See third_party/EonTimer-LICENSE.md.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
#include <limits.h>

#ifndef CREATE_WAITABLE_TIMER_HIGH_RESOLUTION
#define CREATE_WAITABLE_TIMER_HIGH_RESOLUTION 0x00000002
#endif

namespace {
constexpr int abi = 1;
constexpr int max_ms = 1000000;
struct Stage {
    int target, wall_origin, wall_elapsed, status;
    int64_t origin, elapsed_us, error_us;
};
SRWLOCK guard = SRWLOCK_INIT;
Stage stages[3] = {};
int driver = -1, attempt = 0, ready = 0;
int64_t frequency = 0;
HANDLE timer = nullptr;
struct Lock {
    Lock() { AcquireSRWLockExclusive(&guard); }
    ~Lock() { ReleaseSRWLockExclusive(&guard); }
};
int64_t now() {
    LARGE_INTEGER tick;
    return QueryPerformanceCounter(&tick) ? tick.QuadPart : -1;
}
int64_t us(int64_t ticks) {
    // Avoid multiplying an arbitrarily large QPC epoch by 1,000,000.
    return ticks / frequency * 1000000 + ticks % frequency * 1000000 / frequency;
}
int valid(int stage) { return ready && attempt > 0 && stage >= 0 && stage < 3; }
}

extern "C" __declspec(dllexport) int __cdecl CT_Init(int version, int mode, int seed, int f1, int f2) {
    Lock lock;
    ready = 0;
    attempt = 0;
    if (timer) { CloseHandle(timer); timer = nullptr; }
    if (version != abi || (mode != 0 && mode != 1) || seed <= 0 || seed > max_ms ||
        f1 <= 0 || f1 >= f2 || f2 > max_ms) return -1;
    LARGE_INTEGER freq;
    if (!QueryPerformanceFrequency(&freq) || freq.QuadPart <= 0 || freq.QuadPart > 10000000000LL) return -2;
    frequency = freq.QuadPart;
    // Require Windows 10's high-resolution timer; no silent coarse fallback.
    timer = CreateWaitableTimerExW(nullptr, nullptr, CREATE_WAITABLE_TIMER_HIGH_RESOLUTION,
                                 TIMER_MODIFY_STATE | SYNCHRONIZE);
    if (!timer) return -3;
    driver = mode;
    stages[0] = {seed}; stages[1] = {f1}; stages[2] = {f2};
    ready = 1;
    return 1;
}

extern "C" __declspec(dllexport) int __cdecl CT_Round(int number) {
    Lock lock;
    if (!ready || number < 0 || number > 20 || (number && number != attempt + 1)) return -1;
    if (number == 0 && attempt != 0) return -1;
    attempt = number;
    for (auto& s : stages) {
        int target = s.target;
        s = {target};
    }
    return 1;
}

extern "C" __declspec(dllexport) int __cdecl CT_Info(int field) {
    Lock lock;
    switch (field) {
        case 0: return driver;
        case 1: return ready && attempt > 0;
        case 2: return attempt;
        case 3: return abi;
        case 4: return static_cast<int>(frequency / 1000);
        case 5: return static_cast<int>(frequency % 1000);
        case 6: return ready;
        default: return -1;
    }
}

extern "C" __declspec(dllexport) int __cdecl CT_Origin(int stage, int wall_ms) {
    Lock lock;
    if (!ready || stage < 0 || stage > 1 || wall_ms < 0) return -1;
    if (!attempt) return wall_ms; // Round zero stays entirely native.
    if (stages[stage].status != 0 || (stage == 1 && stages[0].status != 2)) return -2;
    int64_t tick = now();
    if (tick < 0) return -3;
    stages[stage].origin = tick;
    stages[stage].wall_origin = wall_ms;
    stages[stage].status = 1;
    if (stage == 1) { // F1 and total F2 share precisely the same origin.
        stages[2].origin = tick;
        stages[2].wall_origin = wall_ms;
        stages[2].status = 1;
    }
    return wall_ms;
}

extern "C" __declspec(dllexport) int __cdecl CT_Step(int stage) {
    Lock lock;
    if (!valid(stage) || driver != 1 || stages[stage].status != 1 ||
        (stage == 2 && stages[1].status != 2)) return -1;
    auto& s = stages[stage];
    int64_t deadline = s.origin + frequency * s.target / 1000;
    int64_t current = now();
    if (current < s.origin) return -2;
    if (current >= deadline) return 1;
    int64_t remaining_us = us(deadline - current);
    if (remaining_us > 2000) {
        // The FFI has no CancellationToken: return to ECS at least every 8 ms
        // of planned sleep (10 ms wait timeout), so its existing stop works.
        int64_t sleep_us = remaining_us - 2000;
        if (sleep_us > 8000) sleep_us = 8000;
        LARGE_INTEGER due;
        due.QuadPart = -sleep_us * 10;
        if (!SetWaitableTimerEx(timer, &due, 0, nullptr, nullptr, nullptr, 0)) return -3;
        DWORD result = WaitForSingleObject(timer, 10);
        if (result != WAIT_OBJECT_0 && result != WAIT_TIMEOUT) return -4;
        return now() >= deadline ? 1 : 0;
    }
    do {
        YieldProcessor();
        current = now();
        if (current < s.origin) return -2;
    } while (current < deadline);
    return 1;
}

extern "C" __declspec(dllexport) int __cdecl CT_Mark(int stage, int wall_ms) {
    // Timestamp immediately on entry, before lock acquisition/data formatting.
    int64_t tick = now();
    Lock lock;
    if (!valid(stage) || stages[stage].status != 1 || tick < stages[stage].origin || wall_ms < 0 ||
        (stage == 2 && stages[1].status != 2)) return -1;
    auto& s = stages[stage];
    int64_t elapsed = us(tick - s.origin);
    int64_t wall_elapsed = static_cast<int64_t>(wall_ms) - s.wall_origin;
    if (elapsed < 0 || elapsed > INT_MAX || wall_elapsed < INT_MIN || wall_elapsed > INT_MAX) return -2;
    s.elapsed_us = elapsed;
    s.error_us = elapsed - static_cast<int64_t>(s.target) * 1000;
    s.wall_elapsed = static_cast<int>(wall_elapsed);
    s.status = 2;
    return 1;
}

extern "C" __declspec(dllexport) int __cdecl CT_Get(int stage, int field) {
    Lock lock;
    if (!ready || stage < 0 || stage > 2) return -1;
    auto& s = stages[stage];
    switch (field) {
        case 0: return s.status;
        case 1: return s.target;
        case 2: return static_cast<int>(s.elapsed_us);
        case 3: return static_cast<int>(s.error_us);
        case 4: return s.wall_elapsed;
        case 5: return static_cast<int>(s.origin % INT_MAX); // shared-origin diagnostic
        default: return -1;
    }
}

extern "C" __declspec(dllexport) int __cdecl CT_Close() {
    Lock lock;
    if (timer) { CloseHandle(timer); timer = nullptr; }
    ready = attempt = 0;
    return 1;
}

BOOL WINAPI DllMain(HINSTANCE, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_DETACH && timer) CloseHandle(timer);
    return TRUE;
}
