using System.Collections.Immutable;
using System.Text;
using System.Text.RegularExpressions;
using EasyCon.Script;
using EasyCon.Script.Syntax;
using EasyScript;

Console.OutputEncoding = Encoding.UTF8;
if (args.Length != 2) throw new ArgumentException("Pass the two English training main.ecs paths; offline only.");
foreach (var path in args)
{
    var labels = Directory.EnumerateFiles(Path.Combine(Path.GetDirectoryName(path)!, "ImgLabel"), "*.IL")
        .Select(p => Path.GetFileNameWithoutExtension(p)).ToImmutableHashSet();
    var errors = Compilation.Create(SyntaxTree.Load(path)).Compile(labels).Where(d => d.IsError).ToArray();
    foreach (var d in errors) Console.WriteLine($"{path}:{d.Location.StartLine + 1}: {d.Message}");
    if (errors.Length != 0) return 1;
    Console.WriteLine($"Pinned 164a full compilation: {Directory.GetParent(path)!.Name}; errors=0");
}
var source = File.ReadAllText(args[0]).Replace("\r\n", "\n");
string Function(string name)
{
    var match = Regex.Match(source, "^FUNC " + Regex.Escape(name) + @"(?:\([^\n]*\))?(?:\s*:\s*(?:INT|STRING))?\n.*?^ENDFUNC$",
        RegexOptions.Multiline | RegexOptions.Singleline);
    if (!match.Success) throw new Exception("Missing actual test producer function: " + name);
    return match.Value + "\n";
}
var header = source[..source.IndexOf("IF $训练准备确认", StringComparison.Ordinal)];
var pure = new StringBuilder(header);
foreach (var name in new[] { "训练累计击倒EV", "训练记录经验状态", "训练计算能力", "训练取种族值", "训练取EV产出",
                             "训练输出开始", "训练输出击倒", "训练输出观测" })
    pure.AppendLine(Function(name));
pure.AppendLine("$native_result = 0");
int checks = 0;
void Assert(string expression, int expected, string label)
{
    checks++;
    pure.AppendLine($"$native_result = {expression}\nIF $native_result != {expected}\n    PRINT ASSERT_FAIL:{label}\n    RETURN\nENDIF");
}
pure.AppendLine("$训练EV = [0,0,0,0,0,0]\n$训练总EV = 0\n$训练倍率 = 1\n$训练敌图鉴 = 51\nCALL 训练累计击倒EV");
Assert("$训练EV[5]", 2, "dugtrio-two-speed");
Assert("$训练击倒序号", 1, "single-commit");
pure.AppendLine("$训练EV = [250,250,0,0,0,5]\n$训练总EV = 505\n$训练倍率 = 4\n$训练敌图鉴 = 386\nCALL 训练累计击倒EV");
Assert("$训练EV[1]", 254, "native-atk-first");
Assert("$训练EV[5]", 6, "native-speed-before-spa");
Assert("$训练EV[3]", 0, "cap-leaves-no-spa");
Assert("$训练总EV", 510, "total-cap");
pure.AppendLine("$训练EV = [0,254,0,0,0,0]\n$训练总EV = 254\n$训练倍率 = 4\n$训练敌图鉴 = 57\nCALL 训练累计击倒EV");
Assert("$训练EV[1]", 255, "individual-cap");

pure.AppendLine("$训练需要经验条数 = 2\n$训练经验条数 = 0\n$训练经验已显示 = 0\n$训练经验低分连续 = 0");
Assert("训练记录经验状态(94)", 0, "low-confidence-not-a-receipt");
Assert("$训练经验条数", 0, "low-confidence-no-count");
Assert("训练记录经验状态(96)", 1, "first-xp");
Assert("训练记录经验状态(97)", 0, "persistent-xp-not-duplicate");
Assert("训练记录经验状态(60)", 0, "one-low");
Assert("训练记录经验状态(96)", 0, "one-low-not-rearmed");
Assert("训练记录经验状态(60)", 0, "gap-one");
Assert("训练记录经验状态(94)", 0, "gray-resets-gap");
Assert("训练记录经验状态(60)", 0, "new-gap-one");
Assert("训练记录经验状态(60)", 0, "new-gap-two");
Assert("训练记录经验状态(96)", 1, "second-recipient");
Assert("$训练经验条数", 2, "two-receipts");
pure.AppendLine("$native_result = 训练记录经验状态(60)\n$native_result = 训练记录经验状态(60)");
Assert("训练记录经验状态(96)", -1, "third-recipient-rejected");
Assert("$训练EV[1]", 255, "receipt-processing-does-not-mutate-ev");

foreach (var level in new[] { 5, 49, 99 })
foreach (var ev in new[] { 0, 3, 4, 255 })
foreach (var iv in new[] { 0, 31 })
for (int nature = 0; nature < 25; nature++)
for (int stat = 0; stat < 6; stat++)
{
    int value = (2 * 65 + iv + ev / 4) * level / 100 + (stat == 0 ? level + 10 : 5);
    var mapping = new[] { -1, 0, 1, 3, 4, 2 };
    if (stat > 0 && nature / 5 != nature % 5)
    {
        if (mapping[stat] == nature / 5) value = value * 11 / 10;
        if (mapping[stat] == nature % 5) value = value * 9 / 10;
    }
    Assert($"训练计算能力(65,{iv},{ev},{level},{nature},{stat})", value,
           $"stat-{level}-{ev}-{iv}-{nature}-{stat}");
}
pure.AppendLine("$训练图鉴 = 292");
Assert("训练计算能力(1,31,255,99,0,0)", 1, "shedinja-hp");
pure.AppendLine("$训练游戏 = 0");
Assert("训练取种族值(386,1)", 180, "deoxys-fr-atk");
pure.AppendLine("$训练游戏 = 1");
Assert("训练取种族值(386,2)", 160, "deoxys-lg-def");

// Emit real producer PRINT output for replay by Python, not handcrafted protocol strings.
pure.AppendLine("""
$训练会话 = "native_training_test"
$训练队伍位置 = 1
$训练图鉴 = 1
$训练初始等级 = 5
$训练等级 = 5
$训练性格 = 0
$训练击倒序号 = 0
$训练源名 = "STATIC"
$训练原地点 = ""
$训练接收方式 = "PARTICIPANT"
$训练强制锻炼器 = 0
$训练曾感染病毒 = 0
$训练EV = [0,0,0,0,0,0]
$训练总EV = 0
$训练倍率 = 1
$训练能力 = [21,11,11,11,13,11]
$训练重算名 = "INITIAL"
PRINT SIDREV|META|TID=12345
CALL 训练输出开始
CALL 训练输出观测
$训练敌图鉴 = 16
CALL 训练累计击倒EV
CALL 训练输出击倒
$训练等级 = 6
$训练能力 = [23,12,12,12,14,12]
$训练重算名 = "LEVEL_UP"
CALL 训练输出观测
$训练会话 = "native_share_test"
$训练队伍位置 = 2
$训练接收方式 = "EXP_SHARE"
$训练等级 = 5
$训练击倒序号 = 0
$训练EV = [0,0,0,0,0,0]
$训练总EV = 0
$训练能力 = [21,11,11,11,13,11]
$训练重算名 = "INITIAL"
CALL 训练输出开始
CALL 训练输出观测
$训练敌图鉴 = 16
CALL 训练累计击倒EV
CALL 训练输出击倒
$训练等级 = 6
$训练能力 = [23,12,12,12,14,12]
$训练重算名 = "LEVEL_UP"
CALL 训练输出观测
PRINT NATIVE_TRAINING_PASS
""");
var compilation = Compilation.Create(SyntaxTree.Parse(pure.ToString()));
var diagnostics = compilation.Compile(null).Where(d => d.IsError).ToArray();
foreach (var d in diagnostics) Console.WriteLine($"Pure check {d.Location.StartLine + 1}: {d.Message}");
if (diagnostics.Length != 0) return 1;
if (compilation.KeyAction || compilation.NeedIL) throw new Exception("Pure checks must never read images or operate hardware.");
var output = new CheckOutput();
using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(55));
compilation.Evaluate(output, null, null, ImmutableDictionary<string, Func<int>>.Empty, timeout.Token);
Console.WriteLine($"Native training checks: {checks}; pass={output.Passed && !output.Failed}; hardware=false");
return output.Passed && !output.Failed ? 0 : 1;

sealed class CheckOutput : IOutputAdapter
{
    public bool Passed { get; private set; }
    public bool Failed { get; private set; }
    public void Print(string message, bool newline)
    {
        if (message.Contains("ASSERT_FAIL")) { Failed = true; Console.WriteLine(message); }
        if (message.Contains("NATIVE_TRAINING_PASS")) Passed = true;
        if (message.StartsWith("SIDTRAIN|") || message.StartsWith("SIDREV|")) Console.WriteLine(message);
    }
    public void Alert(string message) => throw new Exception(message);
}
