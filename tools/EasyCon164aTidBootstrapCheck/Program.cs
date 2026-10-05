using System.Collections.Immutable;
using System.Text;
using System.Text.RegularExpressions;
using EasyCon.Script;
using EasyCon.Script.Syntax;
using EasyScript;

Console.OutputEncoding = Encoding.UTF8;
if (args.Length != 1) throw new ArgumentException("Pass the standalone bootstrap ECS beside its ImgLabel folder.");
var path = Path.GetFullPath(args[0]);
var source = File.ReadAllText(path);
var labels = Directory.EnumerateFiles(Path.Combine(Path.GetDirectoryName(path)!, "ImgLabel"), "*.IL")
    .Select(p => Path.GetFileNameWithoutExtension(p)).ToImmutableHashSet();
var full = Compilation.Create(SyntaxTree.Load(path));
var errors = full.Compile(labels).Where(d => d.IsError).ToArray();
foreach (var d in errors) Console.WriteLine($"{d.Location.StartLine + 1}: {d.Message}");
if (errors.Length != 0) return 1;
Console.WriteLine("1.6.4-a full bootstrap compilation: errors=0");

string Function(string name)
{
    var match = Regex.Match(source, "^FUNC " + Regex.Escape(name) + @"\([^\r\n]*\)\s*:\s*INT\r?\n.*?^ENDFUNC\s*$",
        RegexOptions.Multiline | RegexOptions.Singleline);
    if (!match.Success) throw new Exception($"Missing actual test function: {name}");
    return match.Value + "\n";
}
var pure = new StringBuilder("$native_result = 0\n$测试OP修正次数 = 0\n$测试OP修正上限 = 10\n$测试OP修正MS = 0\n");
pure.Append(Function("测试_判定存档状态"));
pure.Append(Function("测试_判定语速"));
pure.Append(Function("测试_增加OP等待"));
var checks = 0;
void AssertCall(string call, int expected, string name)
{
    pure.AppendLine($"$native_result = {call}\nIF $native_result != {expected}\n    PRINT ASSERT_FAIL:{name}\n    RETURN\nENDIF");
    checks++;
}
int[] scores = [0, 94, 95, 96, 100];
foreach (var saved in scores)
foreach (var empty in scores)
{
    var expected = saved >= 95 && empty >= 95 ? -1 : saved >= 95 ? 1 : empty >= 95 ? 2 : 0;
    AssertCall($"测试_判定存档状态({saved}, {empty})", expected, $"menu-{saved}-{empty}");
}
foreach (var fast in scores)
foreach (var mid in scores)
foreach (var slow in scores)
{
    var expected = fast >= 95 && fast > mid && fast > slow ? 0
        : mid >= 95 && mid > fast && mid > slow ? 1
        : slow >= 95 && slow > fast && slow > mid ? 2 : -1;
    AssertCall($"测试_判定语速({fast}, {mid}, {slow})", expected, $"speed-{fast}-{mid}-{slow}");
}
for (var i = 1; i <= 10; i++)
{
    AssertCall("测试_增加OP等待()", 1, $"op-allow-{i}");
    pure.AppendLine($"IF $测试OP修正次数 != {i} or $测试OP修正MS != {i * 50}\n    PRINT ASSERT_FAIL:op-state-{i}\n    RETURN\nENDIF");
}
AssertCall("测试_增加OP等待()", 0, "op-cap");
pure.AppendLine("IF $测试OP修正次数 != 10 or $测试OP修正MS != 500\n    PRINT ASSERT_FAIL:op-cap-state\n    RETURN\nENDIF");
pure.AppendLine("PRINT NATIVE_TID_BOOTSTRAP_PASS");
var compilation = Compilation.Create(SyntaxTree.Parse(pure.ToString()));
var diagnostics = compilation.Compile(null).Where(d => d.IsError).ToArray();
foreach (var d in diagnostics) Console.WriteLine($"{d.Location.StartLine + 1}: {d.Message}");
if (diagnostics.Length != 0) return 1;
// Deliberately evaluate only actual arithmetic helpers, never the full pad script.
if (compilation.KeyAction || compilation.NeedIL) throw new Exception("Native test must not access hardware or labels.");
var output = new TestOutput();
using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(30));
compilation.Evaluate(output, null, null, ImmutableDictionary<string, Func<int>>.Empty, timeout.Token);
Console.WriteLine($"Native bootstrap decision/OP cases: {checks}, pass={output.Passed && !output.Failed}");
return output.Passed && !output.Failed ? 0 : 1;

sealed class TestOutput : IOutputAdapter
{
    public bool Passed { get; private set; }
    public bool Failed { get; private set; }
    public void Print(string message, bool newline)
    {
        if (message.Contains("ASSERT_FAIL")) { Failed = true; Console.WriteLine(message); }
        if (message.Contains("NATIVE_TID_BOOTSTRAP_PASS")) Passed = true;
    }
    public void Alert(string message) => throw new Exception(message);
}
