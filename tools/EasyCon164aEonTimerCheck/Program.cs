using System.Collections.Immutable;
using System.Text;
using EasyCon.Script;
using EasyCon.Script.Syntax;
using EasyScript;

Console.OutputEncoding = Encoding.UTF8;
if (args.Length < 2) throw new ArgumentException("Pass runtime.ecs, then generated main.ecs paths. Offline only.");
foreach (var path in args.Skip(1))
{
    var labels = Directory.EnumerateFiles(Path.Combine(Path.GetDirectoryName(path)!, "ImgLabel"), "*.IL")
        .Select(p => Path.GetFileNameWithoutExtension(p)!).ToImmutableHashSet();
    var diagnostics = Compilation.Create(SyntaxTree.Load(path)).Compile(labels).Where(d => d.IsError).ToArray();
    foreach (var d in diagnostics) Console.WriteLine($"{path}:{d.Location.StartLine + 1}: {d.Message}");
    if (diagnostics.Length > 0) return 1;
    Console.WriteLine($"Full pinned 164a compilation passed: {path}");
}
var runtime = File.ReadAllText(args[0]).Replace("\r\n", "\n");
var source = new StringBuilder(runtime + "\n");
source.AppendLine("""
$目标SeedMS = 30000
$目标消耗帧 = 3000
$F1阶段脚本固定延迟 = 3500
$F2阶段脚本固定延迟 = 4200
$F1阶段脚本固定帧 = 210
$F2阶段脚本固定帧 = 504
$F1等待帧 = 0
$F2等待帧 = 0
$SeedMS = 30000
$F1等待MS = 0
$F2等待MS = 0
$TV等待MS = 0
$TV等待帧 = 0
$帧轴菜单奇偶开关 = 0
$进入TV = 0
$静态或野生 = "野生"
$道具乱数模式 = 0
$循环计数 = 1
$本轮候选命中计数 = 1
$本轮真值解 = 1
$命中SeedMS = 30020
$命中消耗帧 = 3002
$check_result = 0

FUNC EON伊机控等待参数(): INT
    $F1等待帧 = 0
    $F2等待帧 = 2286
    $F1等待MS = 0
    $F2等待MS = 19050
    RETURN 1
ENDFUNC
FUNC EON伊机控自动校准(): INT
    $SeedMS = 29990
    $check_result = EON伊机控等待参数()
    $循环计数 += 1
    RETURN 1
ENDFUNC
""");
var checks = 0;
void Assert(string name, string expression)
{
    checks++;
    source.AppendLine($"IF {expression}\n    PRINT ASSERT_FAIL:{name}\n    RETURN\nENDIF");
}
foreach (var multiplier in new[] { 1, 2 })
foreach (var frames in Enumerable.Range(-100, 201).Concat(new[] { -1000000, -10000, -2000, 2000, 16230, 1000000 }))
{
    var expected = (int)Math.Round(1000.0 / 59.7275 * frames / multiplier);
    source.AppendLine($"$check_result = EON换算毫秒({frames}, {multiplier})");
    Assert($"gba-{frames}-{multiplier}", $"$check_result != {expected}");
}
foreach (var frames in Enumerable.Range(0, 14))
{
    source.AppendLine($"$check_result = EON除二({frames})");
    Assert($"half-{frames}", $"$check_result != {(int)Math.Round(frames / 2.0)}");
}
source.AppendLine("$check_result = 重新计算等待参数()");
Assert("initial", "$check_result != 1 or $EONF1目标帧 != 210 or $EONF2目标帧 != 1395 or $EONSeed校准MS != 0");
Assert("initial-applied", "$SeedMS != 30000 or $F1等待MS != 16 or $F2等待MS != 19156 or $帧轴菜单奇偶开关 != 0 or $TV等待MS != 0");
source.AppendLine("$check_result = 执行自动校准与等待更新()");
Assert("first-unique", "$check_result != 1 or $EON更新次数 != 1 or $EONSeed校准MS != -20 or $EONF2校准MS != -17 or $SeedMS != 29980");
source.AppendLine("$命中SeedMS = 29990\n$命中消耗帧 = 2999\n$check_result = 执行自动校准与等待更新()");
Assert("additive-and-odd", "$EON更新次数 != 2 or $EONSeed校准MS != -10 or $EONF2校准MS != -9 or $EONF1目标帧 != 210");
source.AppendLine("$本轮候选命中计数 = 2\n$命中SeedMS = 30100\n$命中消耗帧 = 3100\n$check_result = 执行自动校准与等待更新()");
Assert("ambiguous-freeze", "$EON更新次数 != 2 or $EON跳过次数 != 1 or $EONSeed校准MS != -10 or $EONF2校准MS != -9");
source.AppendLine("$本轮候选命中计数 = 1\n$本轮真值解 = 0\n$check_result = 执行自动校准与等待更新()");
Assert("truth-freeze", "$EON更新次数 != 2 or $EON跳过次数 != 2 or $EONF2校准MS != -9");
source.AppendLine("$EONF2校准MS = -1000000\n$SeedMS = 12345\n$check_result = EON应用计时()");
Assert("unreachable-no-fallback", "$check_result != 0 or $SeedMS != 12345");
source.AppendLine("$进入TV = 1\n$check_result = 重新计算等待参数()");
Assert("tv-stop", "$check_result != 0");
source.AppendLine("PRINT NATIVE_EONTIMER_PASS");
var compilation = Compilation.Create(SyntaxTree.Parse(source.ToString()));
var errors = compilation.Compile(null).Where(d => d.IsError).ToArray();
foreach (var d in errors) Console.WriteLine($"Pure ECS {d.Location.StartLine + 1}: {d.Message}");
if (errors.Length > 0) return 1;
if (compilation.KeyAction || compilation.NeedIL) throw new Exception("Offline tests must not press buttons or read capture/labels.");
using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(30));
var output = new CheckOutput();
compilation.Evaluate(output, null, null, ImmutableDictionary<string, Func<int>>.Empty, timeout.Token);
if (!output.Passed || output.Failed) throw new Exception("Native EonTimer checks failed.");
Console.WriteLine($"Native ECS checks={checks}, hardware=false");
return 0;

sealed class CheckOutput : IOutputAdapter
{
    public bool Passed { get; private set; }
    public bool Failed { get; private set; }
    public void Print(string message, bool newline)
    {
        Console.WriteLine(message);
        Passed |= message == "NATIVE_EONTIMER_PASS";
        Failed |= message.StartsWith("ASSERT_FAIL:");
    }
    public void Alert(string message) => throw new Exception(message);
}
