using System.Collections.Immutable;
using System.Text;
using System.Text.RegularExpressions;
using EasyCon.Script;
using EasyCon.Script.Syntax;
using EasyScript;

Console.OutputEncoding = Encoding.UTF8;
if (args.Length != 1) throw new ArgumentException("Pass the generated formal TID ECS beside ImgLabel.");
var path = Path.GetFullPath(args[0]);
var source = File.ReadAllText(path).Replace("\r\n", "\n");
var labels = Directory.EnumerateFiles(Path.Combine(Path.GetDirectoryName(path)!, "ImgLabel"), "*.IL")
    .Select(p => Path.GetFileNameWithoutExtension(p)).ToImmutableHashSet();
var errors = Compilation.Create(SyntaxTree.Load(path)).Compile(labels).Where(d => d.IsError).ToArray();
foreach (var d in errors) Console.WriteLine($"{d.Location.StartLine + 1}: {d.Message}");
if (errors.Length != 0) return 1;
Console.WriteLine("1.6.4-a full formal TID compilation: errors=0");

string Function(string name)
{
    var match = Regex.Match(source, "^FUNC " + Regex.Escape(name) + @"(?:\([^\n]*\))?(?:\s*:\s*INT)?\n.*?^ENDFUNC$",
        RegexOptions.Multiline | RegexOptions.Singleline);
    if (!match.Success) throw new Exception($"Missing actual function: {name}");
    return match.Value + "\n";
}
var pure = new StringBuilder("""
$native_result = 0
$native_time = 0
$native_read = 0
$native_saved = [0, 0, 0]
$native_missing = [0, 0, 0]
$native_pair_cost = 0
$native_op_input = 0
$native_op_retry = 1
$native_retry_count = 0
$native_created = 0
$native_cleared = 0
$native_settings_result = 1
$OP检查起点 = 0
$OP检查截止 = 0
$OP连续匹配 = 0
$OP检查耗时 = 0
$OP检查剩余 = 0
$OP界面匹配分 = 0
$OP无存档匹配分 = 0
$OP存档状态 = 0
$OP新建存档检查 = 0
$OP可重试 = 0
$TID建档已尝试 = 0
$TID建档等待验证 = 0
$TID建档结果 = 0
$TID建档FAST分 = 0
$TID建档MID分 = 0
$TID建档SLOW分 = 0
$连续流程_游戏版本 = 0
$denoise_hit_count = 0
""" + "\n");
pure.Append(Function("TID建档_判定存档状态"));
pure.Append(Function("TID建档_判定语速"));
var detector = Function("TID_检测新建存档")
    .Replace("TIME()", "$native_time")
    .Replace("@存档", "$native_saved[$native_read]")
    .Replace("@无存档", "$native_missing[$native_read]\n        $native_read += 1\n        $native_time += $native_pair_cost")
    .Replace("WAIT $OP检查剩余", "$native_time += $OP检查剩余");
pure.Append(detector);
var marker = source.IndexOf("# TID_AUTO_BOOTSTRAP_ENTRY_BEGIN", StringComparison.Ordinal);
var lastCall = marker >= 0 ? source.LastIndexOf("$OP新建存档检查 = TID_检测新建存档()", marker, StringComparison.Ordinal) : -1;
var endMarker = source.IndexOf("# TID_AUTO_BOOTSTRAP_ENTRY_END", StringComparison.Ordinal);
if (lastCall < 0 || endMarker <= marker) throw new Exception("Missing actual bootstrap entry, including the original OP recovery.");
var start = source.LastIndexOf('\n', lastCall) + 1;
var end = source.IndexOf('\n', endMarker) + 1;
var entry = source[start..end];
var prefix = entry.Contains("CALL EN_清空窗口") ? "EN" : "JP";
var guard = entry
    .Replace("$OP新建存档检查 = TID_检测新建存档()", "$OP新建存档检查 = $native_op_input")
    .Replace("CALL TID建档_创建新游戏", "$native_created += 1")
    .Replace("$TID建档结果 = TID建档_设置语速并首次保存()", "$TID建档结果 = $native_settings_result");
guard = Regex.Replace(guard, @"(?m)^(\s*)RETURN\s*$", "$1RETURN 0");
guard = Regex.Replace(guard, @"(?m)^(\s*)CONTINUE\s*$", "$1RETURN 2");
pure.AppendLine("FUNC NativeEntry(): INT\n" + guard + "    RETURN 1\nENDFUNC");
pure.AppendLine($"FUNC {prefix}_清空窗口\n    $native_cleared += 1\nENDFUNC");
pure.AppendLine("FUNC TID_增加OP修正(): INT\n    $native_retry_count += 1\n    RETURN $native_op_retry\nENDFUNC");
var checks = 0;
void AssertCall(string expression, int expected, string name)
{
    pure.AppendLine($"$native_result = {expression}\nIF $native_result != {expected}\n    PRINT ASSERT_FAIL:{name}\n    RETURN\nENDIF");
    checks++;
}
foreach (var saved in new[] { 0, 94, 95, 96, 100 })
foreach (var missing in new[] { 0, 94, 95, 96, 100 })
    AssertCall($"TID建档_判定存档状态({saved}, {missing})",
        saved >= 95 && missing >= 95 ? -1 : saved >= 95 ? 1 : missing >= 95 ? 2 : 0,
        $"classifier-{saved}-{missing}");
var samples = new[]
{
    (new[] {99,99,0}, new[] {0,0,0}, 1, 2, 500, 0),
    (new[] {0,99,99}, new[] {0,0,0}, 1, 3, 500, 0),
    (new[] {99,0,99}, new[] {0,0,0}, 0, 3, 500, 0),
    (new[] {0,0,0}, new[] {96,0,0}, 2, 1, 500, 0),
    (new[] {0,0,0}, new[] {0,95,0}, 2, 2, 500, 0),
    (new[] {0,0,95}, new[] {0,0,95}, -1, 3, 500, 0),
    (new[] {95,0,0}, new[] {95,0,0}, -1, 1, 500, 0),
    (new[] {94,94,94}, new[] {94,94,94}, 0, 3, 500, 0),
    (new[] {99,99,0}, new[] {0,0,0}, 1, 2, 800, 200),
    (new[] {0,0,0}, new[] {96,0,0}, 2, 1, 600, 200),
};
foreach (var (saved, missing, expected, reads, elapsed, cost) in samples)
{
    pure.AppendLine($"$native_time = 0\n$native_read = 0\n$native_saved = [{string.Join(",", saved)}]\n$native_missing = [{string.Join(",", missing)}]\n$native_pair_cost = {cost}");
    AssertCall("TID_检测新建存档()", expected, $"detector-{checks}");
    AssertCall("$native_read", reads, $"reads-{checks}");
    AssertCall("$native_time", elapsed, $"elapsed-{checks}");
}
var cases = new[]
{
    // state, already attempted, verification pending, settings, OP retry,
    // expected return (0 stop/1 normal/2 restart), creations, clears, pending, retry calls.
    (1,0,0,1,1, 1,0,0,0,0),
    (2,0,0,1,1, 2,1,1,1,0),
    (2,1,1,1,1, 0,0,0,1,0),
    (2,1,0,1,1, 0,0,0,0,0),
    (-1,0,0,1,1, 0,0,0,0,0),
    (-1,1,1,1,1, 0,0,0,1,0),
    (2,0,0,0,1, 0,1,0,0,0),
    (1,1,1,1,1, 1,0,0,0,0),
    (1,1,0,1,1, 1,0,0,0,0),
    (0,0,0,1,1, 2,0,1,0,1),
    (0,1,1,1,1, 2,0,1,1,1),
    (0,0,0,1,0, 0,0,1,0,1),
};
foreach (var language in new[] {0,1})
foreach (var (state, attempted, pending, settings, retry, result, created, cleared, finalPending, retryCalls) in cases)
{
    pure.AppendLine($"$连续流程_游戏版本 = {language}\n$native_op_input = {state}\n$TID建档已尝试 = {attempted}\n$TID建档等待验证 = {pending}\n$native_settings_result = {settings}\n$native_op_retry = {retry}\n$native_created = 0\n$native_cleared = 0\n$native_retry_count = 0\n$denoise_hit_count = 4");
    AssertCall("NativeEntry()", result, $"entry-{checks}");
    AssertCall("$native_created", created, $"created-{checks}");
    AssertCall("$native_cleared", cleared, $"cleared-{checks}");
    AssertCall("$TID建档等待验证", finalPending, $"pending-{checks}");
    AssertCall("$native_retry_count", retryCalls, $"retry-{checks}");
    AssertCall("$denoise_hit_count", cleared != 0 ? 0 : 4, $"denoise-{checks}");
}
pure.AppendLine("PRINT NATIVE_TID_BOOTSTRAP_INTEGRATION_PASS");
var compilation = Compilation.Create(SyntaxTree.Parse(pure.ToString()));
var diagnostics = compilation.Compile(null).Where(d => d.IsError).ToArray();
foreach (var d in diagnostics) Console.WriteLine($"{d.Location.StartLine + 1}: {d.Message}");
if (diagnostics.Length != 0) return 1;
if (compilation.KeyAction || compilation.NeedIL) throw new Exception("Offline test must not access keys, real waits or labels.");
var output = new TestOutput();
using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(30));
compilation.Evaluate(output, null, null, ImmutableDictionary<string, Func<int>>.Empty, timeout.Token);
Console.WriteLine($"Native formal bootstrap checks: {checks}, pass={output.Passed && !output.Failed}");
return output.Passed && !output.Failed ? 0 : 1;

sealed class TestOutput : IOutputAdapter
{
    public bool Passed {get; private set;}
    public bool Failed {get; private set;}
    public void Print(string message, bool newline)
    {
        if (message.Contains("ASSERT_FAIL")) {Failed = true; Console.WriteLine(message);}
        if (message.Contains("NATIVE_TID_BOOTSTRAP_INTEGRATION_PASS")) Passed = true;
    }
    public void Alert(string message) => throw new Exception(message);
}
