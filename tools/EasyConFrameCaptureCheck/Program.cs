using System.Text.Json;
using EasyCon2.CLI;

if (args.Length != 1 || File.Exists(args[0]))
    throw new ArgumentException("Pass a new report.json path; existing evidence is never overwritten.");
var checks = 0;
void Check(bool value, string name)
{
    if (!value) throw new Exception(name);
    checks++;
}
void Reject<T>(Action action, string name) where T : Exception
{
    try { action(); }
    catch (T) { checks++; return; }
    throw new Exception(name);
}

// Both the background and the script use the same published implementation.
// A label/OCR request must make a new physical read, never clone last preview.
var reads = 0;
long ticks = 0;
CapturedFrame<FakeFrame>? latest = null;
using (var source = new SynchronizedFrameSource<FakeFrame>(
    () => new(++reads), f => f.Empty, f => latest = f,
    _ => throw new Exception("Unexpected capture failure"), () => ++ticks))
{
    var preview = source.Read(CancellationToken.None)!;
    using (preview.Frame)
    {
        var label = source.Read(CancellationToken.None)!;
        using (label.Frame)
        {
            Check(reads == 2 && label.Frame.Value == 2, "label reused preview");
            Check(label.Sequence == 2 && label.StartedTicks == 3 && label.CompletedTicks == 4,
                "label frame metadata not bound to its read");
            var ocr = source.Read(CancellationToken.None)!;
            using (ocr.Frame)
            {
                Check(reads == 3 && ocr.Frame.Value == 3, "OCR reused label frame");
                Check(latest!.Sequence == 3, "fresh reads did not update shared preview");
                Check(label.Sequence == 2 && label.CompletedTicks == 4 && label.Frame.Value == 2,
                    "matching frame metadata changed when a newer frame arrived");
            }
            Check(!label.Frame.Disposed, "new read disposed the active matching frame");
        }
        Check(!preview.Frame.Disposed, "preview consumer lost its owned frame");
    }
}

var emptyFrame = new FakeFrame(0, true);
var failures = 0;
using (var source = new SynchronizedFrameSource<FakeFrame>(
    () => emptyFrame, f => f.Empty, _ => throw new Exception("empty frame published"), _ => failures++))
{
    Check(source.Read(CancellationToken.None) is null, "empty read used stale fallback");
    Check(emptyFrame.Disposed && failures == 0, "empty frame ownership/GUI zero-score behavior changed");
}
var calls = 0;
using (var source = new SynchronizedFrameSource<FakeFrame>(
    () => { calls++; throw new IOException("driver failed"); }, f => f.Empty, _ => { }, _ => failures++))
{
    Reject<IOException>(() => source.Read(CancellationToken.None), "driver error hidden");
    Reject<InvalidOperationException>(() => source.Read(CancellationToken.None), "failed driver was reused");
    Check(calls == 1 && failures == 1, "capture error must be reported once without cached fallback");
}
var unpublished = new FakeFrame(1);
using (var source = new SynchronizedFrameSource<FakeFrame>(
    () => unpublished, f => f.Empty, _ => throw new IOException("publication failed"), _ => { }))
{
    Reject<IOException>(() => source.Read(CancellationToken.None), "publication failure hidden");
    Check(unpublished.Disposed, "failed publication leaked the read frame");
}

// Reproduce the reported difference without a camera or real timing sleeps:
// a normal encounter has left the blank-frame phase after WAIT 100, while the
// old preview still represents that phase. Reading that cache would falsely
// report shiny; the actual script read must observe the current nonblank phase.
var encounterMs = 0;
CapturedFrame<FakeFrame>? previewCache = null;
using (var source = new SynchronizedFrameSource<FakeFrame>(
    () => new(encounterMs < 100 ? 100 : 53), f => f.Empty,
    f => previewCache = new(new(f.Frame.Value), f.Sequence, f.StartedTicks, f.CompletedTicks),
    _ => throw new Exception("Unexpected encounter fixture failure")))
{
    var background = source.Read(CancellationToken.None)!;
    background.Frame.Dispose();
    var oldBlankScore = previewCache!.Frame.Value;
    previewCache.Frame.Dispose();
    encounterMs += 100;
    var script = source.Read(CancellationToken.None)!;
    using (script.Frame)
    {
        Check(oldBlankScore > 96 && script.Frame.Value <= 96,
            "normal encounter's stale blank frame was reused after WAIT 100");
        Check(script.Sequence > background.Sequence && previewCache!.Sequence == script.Sequence,
            "encounter read did not refresh the shared preview sequence");
    }
    previewCache!.Frame.Dispose();
}

var concurrent = 0;
var overlaps = 0;
var count = 0;
using (var source = new SynchronizedFrameSource<FakeFrame>(
    () =>
    {
        if (Interlocked.Increment(ref concurrent) != 1) Interlocked.Increment(ref overlaps);
        Thread.SpinWait(1000);
        var value = Interlocked.Increment(ref count);
        Interlocked.Decrement(ref concurrent);
        return new(value);
    }, f => f.Empty, _ => { }, _ => { }))
{
    var sequences = new System.Collections.Concurrent.ConcurrentBag<long>();
    await Task.WhenAll(Enumerable.Range(0, 8).Select(_ => Task.Run(() =>
    {
        for (var i = 0; i < 50; i++)
        {
            var frame = source.Read(CancellationToken.None)!;
            using (frame.Frame) sequences.Add(frame.Sequence);
        }
    })));
    Check(overlaps == 0 && count == 400, "background and script read the camera concurrently");
    Check(sequences.Distinct().Count() == 400 && sequences.Min() == 1 && sequences.Max() == 400,
        "shared capture sequence reused or skipped");
}

// A continuously draining producer must not steal the next read from a script
// that is already queued. Use native threads/barriers, not timing sleeps.
using var firstReadEntered = new ManualResetEventSlim();
using var firstReadRelease = new ManualResetEventSlim();
var fairReads = 0;
using (var source = new SynchronizedFrameSource<FakeFrame>(
    () =>
    {
        var value = ++fairReads;
        if (value == 1) { firstReadEntered.Set(); firstReadRelease.Wait(); }
        return new(value);
    }, f => f.Empty, _ => { }, _ => { }))
{
    var producer = Task.Run(() =>
    {
        for (var i = 0; i < 101; i++)
        {
            var f = source.Read(CancellationToken.None)!;
            f.Frame.Dispose();
        }
    });
    if (!firstReadEntered.Wait(TimeSpan.FromSeconds(5))) throw new Exception("fairness producer did not start");
    CapturedFrame<FakeFrame>? scriptFrame = null;
    Exception? scriptError = null;
    var consumer = new Thread(() =>
    {
        try { scriptFrame = source.Read(CancellationToken.None); }
        catch (Exception ex) { scriptError = ex; }
    });
    consumer.Start();
    var wasQueued = SpinWait.SpinUntil(
        () => (consumer.ThreadState & System.Threading.ThreadState.WaitSleepJoin) != 0,
        TimeSpan.FromSeconds(5));
    firstReadRelease.Set();
    await producer.WaitAsync(TimeSpan.FromSeconds(5));
    if (!consumer.Join(TimeSpan.FromSeconds(5))) throw new Exception("fairness consumer did not finish");
    Check(wasQueued && scriptError is null && scriptFrame?.Sequence == 2,
        "background capture stole a queued script read");
    scriptFrame!.Frame.Dispose();
}

// Cancellation interrupts a queued read without another camera call. It is not
// advertised as interrupting a native driver's already-blocked Read operation.
using var entered = new ManualResetEventSlim();
using var release = new ManualResetEventSlim();
using var waiting = new ManualResetEventSlim();
using var cancel = new CancellationTokenSource();
using (var source = new SynchronizedFrameSource<FakeFrame>(
    () => { entered.Set(); release.Wait(); return new(1); }, f => f.Empty, _ => { }, _ => { }))
{
    var producer = Task.Run(() => { var f = source.Read(CancellationToken.None)!; f.Frame.Dispose(); });
    if (!entered.Wait(TimeSpan.FromSeconds(5))) throw new Exception("fixture producer did not start");
    var consumer = Task.Run(() =>
    {
        waiting.Set();
        Reject<OperationCanceledException>(() => source.Read(cancel.Token), "queued capture did not cancel");
    });
    if (!waiting.Wait(TimeSpan.FromSeconds(5))) throw new Exception("fixture consumer did not start");
    cancel.Cancel();
    try { await consumer.WaitAsync(TimeSpan.FromSeconds(5)); }
    finally { release.Set(); }
    await producer.WaitAsync(TimeSpan.FromSeconds(5));
}

using (var report = new FileStream(Path.GetFullPath(args[0]), FileMode.CreateNew))
    JsonSerializer.Serialize(report, new
    {
        hardware_access = false, checks, physical_read_fixture_calls = 400,
        assembly = typeof(SynchronizedFrameSource<FakeFrame>).Assembly.Location,
        scenarios = new[] { "fresh-label", "fresh-OCR", "same-frame-metadata", "consumer-ownership",
            "empty-no-fallback", "driver-error", "publication-error", "normal-encounter-stale-blank",
            "serialized-readers", "queued-script-not-starved", "queued-cancel" }
    }, new JsonSerializerOptions { WriteIndented = true });
Console.WriteLine($"Native synchronized capture: {checks} assertions and 400 serialized reads; hardware=false");

sealed class FakeFrame(int value, bool empty = false) : IDisposable
{
    public int Value { get; } = value;
    public bool Empty { get; } = empty;
    public bool Disposed { get; private set; }
    public void Dispose() => Disposed = true;
}
