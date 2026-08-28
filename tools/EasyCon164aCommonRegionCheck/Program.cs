using System.Collections.Immutable;
using System.Diagnostics;
using System.Text;
using EasyCon.Script;
using EasyCon.Script.Syntax;
using EasyScript;

Console.OutputEncoding = Encoding.UTF8;
if (args.Length == 2 && args[0] == "--compile")
{
    var path = Path.GetFullPath(args[1]);
    var labels = Directory.EnumerateFiles(Path.Combine(Path.GetDirectoryName(path)!, "ImgLabel"), "*.IL")
        .Select(p => Path.GetFileNameWithoutExtension(p)).ToImmutableHashSet();
    var c = Compilation.Create(SyntaxTree.Load(path));
    var errors = c.Compile(labels).Where(d => d.IsError).ToArray();
    foreach (var d in errors) Console.WriteLine($"{d.Location.Text.FileName}:{d.Location.StartLine + 1}: {d.Message}");
    Console.WriteLine($"1.6.4-a compile: {Path.GetFileName(path)}, errors={errors.Length}");
    return errors.Length == 0 ? 0 : 1;
}
if (args.Length < 1 || args.Length > 2) throw new ArgumentException("Pass the common-region ECS asset path [--stress].");
var source = File.ReadAllText(args[0]);
// Standalone arithmetic tests: no labels, pad, OCR or game actions.
source += """

FUNC 取Seed最大索引($game: INT): INT
    RETURN 100000
ENDFUNC
FUNC 取MS($game: INT, $idx: INT): INT
    RETURN $idx * 17
ENDFUNC
FUNC 候选MSE评分($x: INT, $y: INT, $wx: INT, $wy: INT): INT
    RETURN $x * $x * $wx + $y * $y * $wy
ENDFUNC
$test = 0
$round = 0
$point = 0
CALL 共同区重置
$test = 共同区收集配对(40000,1500,100)
$test = 共同区提交()
CALL 共同区开始扫描
$test = 共同区收集配对(40017,1501,101)
$test = 共同区提交()
CALL 共同区开始扫描
$test = 共同区收集配对(40034,1502,102)
$test = 共同区提交()
IF $C_最佳覆盖 != 3 or $C_最佳Seed跨度 != 34 or $C_最佳ADV跨度 != 2 or $C_可用 != 1
    PRINT ASSERT_FAIL: tight-three
    RETURN
ENDIF
$test = 共同区候选加权距离(101,1503,1,1)
IF $test != 1
    PRINT ASSERT_FAIL: score
    RETURN
ENDIF
CALL 共同区重置
FOR $round = 0 TO 3
    CALL 共同区开始扫描
    $test = 共同区收集配对(40000 + $round * 60,1500 + $round * 10,100 + $round)
    $test = 共同区提交()
NEXT
IF $C_最佳覆盖 != 2 or $C_最佳Seed跨度 > 100 or $C_最佳ADV跨度 > 30
    PRINT ASSERT_FAIL: chain
    RETURN
ENDIF
CALL 共同区重置
FOR $round = 0 TO 11
    CALL 共同区开始扫描
    FOR $point = 0 TO 39
        $test = 共同区收集配对(40000 + $point * 17,1400 + $point * 7 + $round,100 + $point)
    NEXT
    $test = 共同区提交()
NEXT
IF $C_轮数 != 12 or $C_最佳覆盖 != 12 or $C_超限 != 0
    PRINT ASSERT_FAIL: twelve-rounds
    RETURN
ENDIF
PRINT NATIVE_COMMON_REGION_PASS
""";
if (args.Length == 2 && args[1] == "--stress")
    source = source.Replace("FOR $point = 0 TO 39", "FOR $point = 0 TO 199")
        .Replace("40000 + $point * 17,1400 + $point * 7 + $round,100 + $point", "40000 + ($point % 40) * 17,1400 + $point * 7 + $round,100 + $point % 40");
var compilation = Compilation.Create(SyntaxTree.Parse(source));
var diagnostics = compilation.Compile(null);
foreach (var d in diagnostics.Where(d => d.IsError))
    Console.WriteLine($"{d.Location.StartLine + 1}: {d.Message}");
if (diagnostics.Any(d => d.IsError)) return 1;
if (compilation.KeyAction || compilation.NeedIL) throw new Exception("Test must not access hardware.");
var output = new CheckOutput();
using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(55));
var timer = Stopwatch.StartNew();
compilation.Evaluate(output, null, null, ImmutableDictionary<string, Func<int>>.Empty, timeout.Token);
Console.WriteLine($"Native evaluation: {timer.ElapsedMilliseconds} ms");
return output.Passed && !output.Failed ? 0 : 1;

sealed class CheckOutput : IOutputAdapter
{
    public bool Passed { get; private set; }
    public bool Failed { get; private set; }
    public void Print(string message, bool newline)
    {
        if (message.Contains("ASSERT_FAIL")) Failed = true;
        if (message.Contains("NATIVE_COMMON_REGION_PASS")) Passed = true;
        if (message.Contains("ASSERT_FAIL") || message.Contains("NATIVE_COMMON_REGION_PASS")) Console.WriteLine(message);
    }
    public void Alert(string message) => throw new Exception(message);
}
