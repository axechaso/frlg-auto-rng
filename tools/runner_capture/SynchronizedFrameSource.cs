using System.Diagnostics;

namespace EasyCon2.CLI;

/// <summary>A caller-owned frame and metadata from the same physical read.</summary>
public sealed record CapturedFrame<T>(T Frame, long Sequence, long StartedTicks, long CompletedTicks)
    where T : class, IDisposable;

/// <summary>
/// Serializes background draining and synchronous script reads on one device.
/// Read never substitutes a previously published preview frame. The caller owns
/// each returned frame; publication must clone anything retained for preview.
/// </summary>
public sealed class SynchronizedFrameSource<T> : IDisposable where T : class, IDisposable
{
    private readonly SemaphoreSlim gate = new(1, 1);
    private readonly Func<T> read;
    private readonly Func<T, bool> empty;
    private readonly Action<CapturedFrame<T>> publish;
    private readonly Action<Exception> failed;
    private readonly Func<long> timestamp;
    private long sequence;
    private Exception? failure;

    public SynchronizedFrameSource(Func<T> read, Func<T, bool> empty,
        Action<CapturedFrame<T>> publish, Action<Exception> failed,
        Func<long>? timestamp = null)
    {
        this.read = read;
        this.empty = empty;
        this.publish = publish;
        this.failed = failed;
        this.timestamp = timestamp ?? Stopwatch.GetTimestamp;
    }

    public CapturedFrame<T>? Read(CancellationToken cancellationToken)
    {
        // Queue all contended callers through the same async waiter path. A
        // synchronous Wait loop could let the draining thread reacquire the
        // permit before an already-waiting script thread gets scheduled.
        gate.WaitAsync(cancellationToken).GetAwaiter().GetResult();
        T? frame = null;
        try
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (failure is not null)
                throw new InvalidOperationException("采集卡读取已失败", failure);
            var started = timestamp();
            frame = read();
            var completed = timestamp();
            if (empty(frame))
            {
                frame.Dispose();
                frame = null;
                return null;
            }
            var captured = new CapturedFrame<T>(frame, ++sequence, started, completed);
            publish(captured);
            return captured;
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            frame?.Dispose();
            throw;
        }
        catch (Exception ex)
        {
            frame?.Dispose();
            if (failure is null)
            {
                failure = ex;
                failed(ex);
            }
            throw;
        }
        finally
        {
            gate.Release();
        }
    }

    // Dispose only after both the script and the background reader have ended.
    public void Dispose() => gate.Dispose();
}
