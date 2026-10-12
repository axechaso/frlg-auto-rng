using System.Collections.Immutable;
using System.Diagnostics;
using System.Text;
using System.Text.RegularExpressions;
using EasyCon.Script;
using EasyCon.Script.Syntax;
using EasyScript;

Console.OutputEncoding = Encoding.UTF8;
if (args.Length < 3) throw new ArgumentException("Pass new evidence directory, asset directory, generated projects. Offline only.");
var evidence = args[0];
var assets = args[1];
var projects = args.Skip(2).ToArray();
foreach (var path in projects)
{
    var labels = Directory.EnumerateFiles(Path.Combine(Path.GetDirectoryName(path)!, "ImgLabel"), "*.IL")
        .Select(p => Path.GetFileNameWithoutExtension(p)!).ToImmutableHashSet();
    var compilation = Compilation.Create(SyntaxTree.Load(path));
    var errors = compilation.Compile(labels).Where(d => d.IsError).ToArray();
    foreach (var d in errors) Console.WriteLine($"{path}:{d.Location.StartLine + 1}: {d.Message}");
    if (errors.Length > 0) return 1;
    Console.WriteLine($"Full pinned 164a clock project compilation passed: {path}");
}
string Function(string text, string name)
{
    var matches = Regex.Matches(text.Replace("\r\n", "\n"), @"(?ms)^FUNC " + Regex.Escape(name) + @"(?:\([^\n]*\))?[^\n]*\n.*?^ENDFUNC$");
    if (matches.Count != 1) throw new Exception($"Expected one function {name}");
    return matches[0].Value;
}
var template = File.ReadAllText(projects[0]);
var wait = Function(template, "执行时间轴等待到");
foreach (var mode in new[] { 0, 1 })
{
    var directory = Path.Combine(evidence, $"pure-{mode}");
    if (Directory.Exists(directory)) throw new Exception("Do not overwrite evidence.");
    Directory.CreateDirectory(Path.Combine(directory, "lib"));
    var dll = Path.Combine(directory, "frlg_clock_test.dll");
    File.Copy(Path.Combine(assets, "frlg_clock_test.dll"), dll);
    var runtime = File.ReadAllText(Path.Combine(assets, "runtime.ecs"))
        .Replace("__DLL__", dll.Replace('\\', '/')).Replace("__DRIVER__", mode.ToString())
        .Replace("__SEED__", "25").Replace("__F1__", "35").Replace("__F2__", "100");
    File.WriteAllText(Path.Combine(directory, "lib/98_clock_test.ecs"), runtime, new UTF8Encoding(false));
    foreach (var (filename, prefix) in new[] { ("16_获取_静态目标.ecs", "静态"), ("17_获取_野生目标.ecs", "野生") })
    {
        var source = File.ReadAllText(Path.Combine(Path.GetDirectoryName(projects[0])!, "lib", filename)).Replace("\r\n", "\n");
        var globals = string.Join('\n', source.Split('\n').TakeWhile(line => !line.StartsWith("FUNC "))
            .Where(line => line.StartsWith("$" + prefix + "目标时间轴")));
        var pure = globals + "\n" + Function(source, "设置" + prefix + "目标时间轴") + "\n" + Function(source, prefix + "目标等待F2");
        File.WriteAllText(Path.Combine(directory, "lib", filename), pure, new UTF8Encoding(false));
    }
    var main = "$时间轴精确尾段MS = 50\n" + wait + "\n" + File.ReadAllText(Path.Combine(assets, "main.ecs")) + "\n" + """
$check = CLOCK开始轮(0)
IF $check != 1 or CT_Info(1) != 0
    PRINT ASSERT_FAIL:round-zero
    RETURN
ENDIF
PRINT FIXEDTEST|V=1|TYPE=INIT|SEED_TARGET=25|ADV_TARGET=10|USED_SEED=25|USED_F1=35|USED_F2=100|LIMIT=2|END=1
FOR $round = 1 TO 2
    PRINT "FIXEDTEST|V=1|TYPE=ATTEMPT|ATTEMPT=" & $round & "|END=1"
    $check = CLOCK开始轮($round)
    $origin = CT_Origin(0, TIME())
    $check = CLOCK等待到(0, $origin, 25)
    IF $check < 0 or CT_Get(0, 0) != 2
        PRINT ASSERT_FAIL:seed
        RETURN
    ENDIF
    $origin = CT_Origin(1, TIME())
    IF CT_Get(1, 5) != CT_Get(2, 5)
        PRINT ASSERT_FAIL:common-origin
        RETURN
    ENDIF
    $check = CLOCK等待到(1, $origin, 35)
    IF $check < 0 or CT_Get(1, 0) != 2
        PRINT ASSERT_FAIL:f1
        RETURN
    ENDIF
    $deadline = $origin + 100
    IF $round == 1
        $check = 设置静态目标时间轴(1, $deadline, 50)
        $check = 静态目标等待F2(0)
    ELSE
        $check = 设置野生目标时间轴(1, $deadline, 50)
        $check = 野生目标等待F2(0)
    ENDIF
    IF $check < 0 or CT_Get(2, 0) != 2
        PRINT ASSERT_FAIL:f2
        RETURN
    ENDIF
    CALL CLOCK输出本轮
    PRINT "FIXEDTEST|V=1|TYPE=ROUND|ATTEMPT=" & $round & "|CANDIDATES=1|TRUTH=1|HIT_SEED=25|HIT_ADV=10|USED_SEED=25|USED_F1=35|USED_F2=100|APPLIED=1|END=1"
NEXT
PRINT FIXEDTEST|V=1|TYPE=STOP|ATTEMPTS=2|END=1
$check = CT_Close()
PRINT NATIVE_CLOCK_PASS
""";
    var path = Path.Combine(directory, "main.ecs");
    File.WriteAllText(path, main, new UTF8Encoding(false));
    var compilation = Compilation.Create(SyntaxTree.Load(path));
    var errors = compilation.Compile(null).Where(d => d.IsError).ToArray();
    foreach (var d in errors) Console.WriteLine($"Pure {d.Location.StartLine + 1}: {d.Message}");
    if (errors.Length > 0) return 1;
    if (compilation.KeyAction || compilation.NeedIL) throw new Exception("Never execute full projects or hardware calls.");
    Console.WriteLine($"BEGIN_DRIVER={mode}");
    var output = new CheckOutput();
    using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(5));
    compilation.Evaluate(output, null, null, ImmutableDictionary<string, Func<int>>.Empty, timeout.Token);
    if (!output.Passed || output.Failed) throw new Exception("Native clock checks failed.");
    Console.WriteLine($"END_DRIVER={mode}");
}
// A separate pure script cancels a long B deadline: the native FFI must yield.
var cancelDir = Path.Combine(evidence, "cancel");
Directory.CreateDirectory(Path.Combine(cancelDir, "lib"));
var cancelDll = Path.Combine(cancelDir, "frlg_clock_test.dll");
File.Copy(Path.Combine(assets, "frlg_clock_test.dll"), cancelDll);
var cancelRuntime = File.ReadAllText(Path.Combine(assets, "runtime.ecs"))
    .Replace("__DLL__", cancelDll.Replace('\\', '/')).Replace("__DRIVER__", "1")
    .Replace("__SEED__", "1000").Replace("__F1__", "1000").Replace("__F2__", "2000");
File.WriteAllText(Path.Combine(cancelDir, "lib/98_clock_test.ecs"), cancelRuntime);
var cancelPath = Path.Combine(cancelDir, "main.ecs");
File.WriteAllText(cancelPath, "$check = CLOCK开始轮(1)\n$origin = CT_Origin(0, TIME())\n$check = CT_Step(0)\nPRINT CANCEL_READY\n$check = CLOCK精确等待(0)\nPRINT ASSERT_FAIL:cancel-reached-end\n");
var cancelCompilation = Compilation.Create(SyntaxTree.Load(cancelPath));
if (cancelCompilation.Compile(null).Any(d => d.IsError) || cancelCompilation.KeyAction || cancelCompilation.NeedIL) throw new Exception("Invalid cancellation fixture.");
var cancelOutput = new CheckOutput();
var elapsed = new Stopwatch();
using (var cancellation = new CancellationTokenSource(TimeSpan.FromSeconds(5)))
{
    cancelOutput.Ready = () => { elapsed.Start(); cancellation.CancelAfter(40); };
    try { cancelCompilation.Evaluate(cancelOutput, null, null, ImmutableDictionary<string, Func<int>>.Empty, cancellation.Token); }
    catch (OperationCanceledException) { }
    if (!elapsed.IsRunning || !cancellation.IsCancellationRequested || cancelOutput.Failed) throw new Exception("Cancellation failed.");
}
if (elapsed.ElapsedMilliseconds > 750) throw new Exception("Native wait did not yield promptly to cancellation.");
Console.WriteLine($"Native cancellation passed: {elapsed.ElapsedMilliseconds} ms; hardware=false");
return 0;

sealed class CheckOutput : IOutputAdapter
{
    public bool Passed { get; private set; }
    public bool Failed { get; private set; }
    public Action? Ready { get; set; }
    public void Print(string message, bool newline)
    {
        Console.WriteLine(message);
        Passed |= message == "NATIVE_CLOCK_PASS";
        Failed |= message.StartsWith("ASSERT_FAIL:");
        if (message == "CANCEL_READY") Ready?.Invoke();
    }
    public void Alert(string message) => throw new Exception(message);
}
