using System.Collections.Immutable;
using System.Text;
using System.Text.RegularExpressions;
using EasyCon.Script;
using EasyCon.Script.Syntax;
using EasyScript;

Console.OutputEncoding = Encoding.UTF8;
if (args.Length < 1) throw new ArgumentException("Pass generated SID traversal main.ecs files. Offline only.");
foreach (var arg in args)
{
    var path = Path.GetFullPath(arg);
    var labels = Directory.EnumerateFiles(Path.Combine(Path.GetDirectoryName(path)!, "ImgLabel"), "*.IL")
        .Select(p => Path.GetFileNameWithoutExtension(p)).ToImmutableHashSet();
    var errors = Compilation.Create(SyntaxTree.Load(path)).Compile(labels).Where(d => d.IsError).ToArray();
    foreach (var d in errors) Console.WriteLine($"{path}:{d.Location.StartLine + 1}: {d.Message}");
    if (errors.Length != 0) return 1;
    Console.WriteLine($"Full pinned 164a compilation: {Directory.GetParent(path)!.Name}, errors=0");
}
var source = File.ReadAllText(args[0]).Replace("\r\n", "\n");
string Function(string name)
{
    var match = Regex.Match(source, "^FUNC " + Regex.Escape(name) + @"(?:\([^\n]*\))?(?:\s*:\s*INT)?\n.*?^ENDFUNC$",
        RegexOptions.Multiline | RegexOptions.Singleline);
    if (!match.Success) throw new Exception("Missing production evidence function: " + name);
    return match.Value + "\n";
}
var globalsStart = source.IndexOf("# SIDTRAVERSAL_PID_OBSERVATION_V1", StringComparison.Ordinal);
var globalsEnd = source.IndexOf("FUNC SID遍历收集匹配PID", globalsStart, StringComparison.Ordinal);
if (globalsStart < 0 || globalsEnd < 0) throw new Exception("Missing production extension globals.");
var pure = new StringBuilder(source[globalsStart..globalsEnd]);
pure.AppendLine("""
$native_result = 0
$native_index = 0
$native_waits = 0
$native_recent_shiny = 0
$native_en_pages = [98, 98, 98]
$native_jp_pages = [40, 40, 40]
$native_stars = [60, 61, 62]
$Seed模式 = 0
$识图阈值 = 95
$本轮候选命中计数 = 0
$PIDHI = 0
$PIDLO = 0
$SID遍历本轮出闪 = 0
$目标全国图鉴编号 = 54
$循环计数 = 0
FUNC 读取最近出闪检测结果(): INT
    RETURN $native_recent_shiny
ENDFUNC
""");
pure.Append(Function("SID遍历收集匹配PID"));
var sampling = Function("SID遍历采样闪光状态")
    .Replace("    FOR $SID遍历采样索引 = 1 TO 3\n", "    FOR $SID遍历采样索引 = 1 TO 3\n        $native_index = $SID遍历采样索引 - 1\n")
    .Replace("@日版性格界面", "$native_jp_pages[$native_index]")
    .Replace("@性格界面", "$native_en_pages[$native_index]")
    .Replace("@出闪", "$native_stars[$native_index]")
    .Replace("WAIT 50", "$native_waits += 1");
pure.Append(sampling);
pure.Append(Function("SID遍历处理反查证据"));
var checks = 0;
void Assert(string expression, long expected, string label)
{
    pure.AppendLine($"$native_result = {expression}\nIF $native_result != {expected}\n    PRINT ASSERT_FAIL:{label}\n    RETURN\nENDIF");
    checks++;
}
// Never restore consistency after a different matching PID was found.
pure.AppendLine("$本轮候选命中计数 = 1\n$PIDHI = 65535\n$PIDLO = 0\nCALL SID遍历收集匹配PID");
Assert("$SID遍历PID一致", 1, "first");
pure.AppendLine("$本轮候选命中计数 = 2\nCALL SID遍历收集匹配PID");
Assert("$SID遍历PID一致", 1, "same-pid-different-method");
pure.AppendLine("$本轮候选命中计数 = 3\n$PIDLO = 1\nCALL SID遍历收集匹配PID");
Assert("$SID遍历PID一致", 0, "different");
pure.AppendLine("$本轮候选命中计数 = 4\n$PIDLO = 0\nCALL SID遍历收集匹配PID");
Assert("$SID遍历PID一致", 0, "no-chain-recovery");

foreach (var language in new[] { 0, 10 })
foreach (var page in new[] { 0, 94, 95, 98 })
foreach (var star in new[] { 60, 90, 91, 94, 95, 98 })
{
    pure.AppendLine($"$Seed模式 = {language}\n$native_en_pages = [{(language == 0 ? page : 40)}, {(language == 0 ? page : 40)}, {(language == 0 ? page : 40)}]");
    pure.AppendLine($"$native_jp_pages = [{(language == 10 ? page : 40)}, {(language == 10 ? page : 40)}, {(language == 10 ? page : 40)}]");
    pure.AppendLine($"$native_stars = [{star}, {star}, {star}]\n$SID遍历本轮出闪 = 0\n$native_recent_shiny = 0\n$native_waits = 0\nCALL SID遍历采样闪光状态");
    var expected = page < 95 ? -1 : star >= 95 ? 1 : star <= 90 ? 0 : -1;
    Assert("$SID遍历闪光状态", expected, $"sample-{language}-{page}-{star}");
    Assert("$native_waits", 2, $"three-frames-{language}-{page}-{star}");
}
pure.AppendLine("$Seed模式 = 0\n$native_en_pages = [98, 98, 98]\n$native_stars = [60, 98, 60]\n$SID遍历本轮出闪 = 0\nCALL SID遍历采样闪光状态");
Assert("$SID遍历闪光状态", -1, "unstable");
pure.AppendLine("$native_stars = [60, 61, 62]\n$native_recent_shiny = 1\nCALL SID遍历采样闪光状态");
Assert("$SID遍历闪光状态", -1, "battle-summary-conflict");
pure.AppendLine("$native_recent_shiny = 0\n$识图阈值 = 90\nCALL SID遍历采样闪光状态");
Assert("$SID遍历证据阈值", 95, "never-adapt-evidence");
pure.AppendLine("$识图阈值 = 95\n$SID遍历候选TID = 12345\n$SID遍历候选SID = 54321\n$本轮候选命中计数 = 3\n$SID遍历PID一致 = 1\n$SID遍历PID高 = 12345\n$SID遍历PID低 = 54321\n$SID遍历本轮出闪 = 0\n$SID遍历闪光状态 = 0");
Assert("SID遍历处理反查证据(1)", 2, "non-target-normal-eliminates");
Assert("$SID遍历PSV", (12345 ^ 54321) >> 3, "xor");
pure.AppendLine("$循环计数 = 1\n$SID遍历PID高 = 65535\n$SID遍历PID低 = 0\n$SID遍历闪光状态 = 1\n$SID遍历星标最低 = 96\n$SID遍历星标最高 = 97\n$SID遍历页面最低 = 98");
Assert("SID遍历处理反查证据(1)", 1, "non-target-shiny-stops");
Assert("$SID遍历PSV", 8191, "unsigned-pid-words");
pure.AppendLine("$SID遍历PID一致 = 0\n$SID遍历本轮出闪 = 1");
Assert("SID遍历处理反查证据(1)", 3, "ambiguous-shiny-preserves-scene");
Assert("SID遍历处理反查证据(0)", 3, "failed-reverse-shiny-preserves-scene");
pure.AppendLine("$SID遍历本轮出闪 = 0\n$SID遍历闪光状态 = -1");
Assert("SID遍历处理反查证据(1)", 0, "ambiguous-normal-not-evidence");
pure.AppendLine("PRINT NATIVE_SID_OBSERVATION_PASS");
var compilation = Compilation.Create(SyntaxTree.Parse(pure.ToString()));
var diagnostics = compilation.Compile(null).Where(d => d.IsError).ToArray();
foreach (var d in diagnostics) Console.WriteLine($"Pure check {d.Location.StartLine + 1}: {d.Message}");
if (diagnostics.Length != 0) return 1;
if (compilation.KeyAction || compilation.NeedIL) throw new Exception("Offline evaluation must never access hardware or real labels.");
var output = new CheckOutput();
using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(30));
compilation.Evaluate(output, null, null, ImmutableDictionary<string, Func<int>>.Empty, timeout.Token);
Console.WriteLine($"Native SID evidence checks: {checks}; pass={output.Passed && !output.Failed}; hardware=false");
return output.Passed && !output.Failed ? 0 : 1;

sealed class CheckOutput : IOutputAdapter
{
    public bool Passed { get; private set; }
    public bool Failed { get; private set; }
    public void Print(string message, bool newline)
    {
        if (message.Contains("ASSERT_FAIL")) { Failed = true; Console.WriteLine(message); }
        if (message.Contains("NATIVE_SID_OBSERVATION_PASS")) Passed = true;
        if (message.StartsWith("SIDTRAVERSAL_OBS|")) Console.WriteLine(message);
    }
    public void Alert(string message) => throw new Exception(message);
}
