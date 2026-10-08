using System.Collections.Immutable;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using EasyCon.Script;
using EasyCon.Script.Syntax;
using EasyScript;

Console.OutputEncoding = Encoding.UTF8;
if (args.Length < 2) throw new ArgumentException("Pass a new report.json path and generated main.ecs files. Offline only.");
if (File.Exists(args[0])) throw new ArgumentException("Report exists; do not overwrite old evidence.");
var reports = new List<object>();
var checks = 0;
foreach (var arg in args.Skip(1))
{
    var path = Path.GetFullPath(arg);
    var directory = Path.GetDirectoryName(path)!;
    var labels = Directory.EnumerateFiles(Path.Combine(directory, "ImgLabel"), "*.IL")
        .Select(p => Path.GetFileNameWithoutExtension(p)).ToImmutableHashSet();
    var errors = Compilation.Create(SyntaxTree.Load(path)).Compile(labels).Where(d => d.IsError).ToArray();
    foreach (var d in errors) Console.WriteLine($"{path}:{d.Location.StartLine + 1}: {d.Message}");
    if (errors.Length != 0) return 1;
    Console.WriteLine($"Full pinned 164a compilation: {Directory.GetParent(path)!.Name}, errors=0");
    var source = File.ReadAllText(path).Replace("\r\n", "\n");
    if (!source.Contains("# GUI_TARGET_SHINY_PRECALIBRATION_V1")) continue;
    using var manifest = JsonDocument.Parse(File.ReadAllText(Path.Combine(directory, "plan.json")));
    var dex = manifest.RootElement.GetProperty("precalibration").GetProperty("target_shiny_success").GetProperty("species_id").GetInt32();
    string Function(string text, string name)
    {
        var match = Regex.Match(text, "^FUNC " + Regex.Escape(name) + @"(?:\([^\n]*\))?(?:\s*:\s*INT)?\n.*?^ENDFUNC$",
            RegexOptions.Multiline | RegexOptions.Singleline);
        if (!match.Success) throw new Exception("Missing production function: " + name);
        return match.Value + "\n";
    }
    var capture = File.ReadAllText(Path.Combine(directory, "lib", "20_识图_抓捕对象名称识别.ecs")).Replace("\r\n", "\n");
    var result = File.ReadAllText(Path.Combine(directory, "lib", "17_获取_野生目标.ecs")).Replace("\r\n", "\n");
    var pure = new StringBuilder("""
$更新预校准 = 1
$道具乱数模式 = 0
$循环计数 = 8
$本轮物种命中 = 1
$目标全国图鉴编号 = 0
$本轮流程结果 = -1
$反查细分成功 = -2
$最近出闪检测结果 = 0
$最近出闪检测图鉴编号 = 0
$野生获取结果_识图失败 = 0
$野生获取结果_图鉴编号 = 0
$Seed累计修正索引 = -7
$消耗帧实际执行修正量 = 23
$native_result = 0
$预校准目标出闪写回结果 = 0

""");
    foreach (var name in new[] { "清空最近出闪检测", "记录最近出闪检测", "读取最近出闪检测结果", "读取最近出闪检测图鉴编号" })
        pure.Append(Function(capture, name));
    foreach (var name in new[] { "读取获取结果识图失败", "读取获取结果图鉴编号" }) pure.Append(Function(result, name));
    pure.Append(Function(source, "记录目标出闪预校准"));
    foreach (var pair in new[] { ("目标获取终止", "$本轮流程结果 == -1"), ("能力页终止", "$反查细分成功 == -2") })
    {
        var block = Regex.Match(source, "^        IF " + Regex.Escape(pair.Item2) + @"\n.*?^        ENDIF$", RegexOptions.Multiline | RegexOptions.Singleline);
        if (!block.Success || !block.Value.Contains("= 记录目标出闪预校准")) throw new Exception("Missing production terminal hook.");
        pure.AppendLine($"FUNC 离线{pair.Item1}\n{block.Value}\nENDFUNC");
    }
    var output = new CheckOutput();
    void Case(string name, int stage, bool save, string changes = "", string? wrapper = null)
    {
        pure.AppendLine($"PRINT CASE:{name}");
        pure.AppendLine($"$更新预校准 = 1\n$道具乱数模式 = 0\n$循环计数 = 8\n$本轮物种命中 = 1\n$目标全国图鉴编号 = {dex}\n$野生获取结果_图鉴编号 = {dex}\n$野生获取结果_识图失败 = 0\n$本轮流程结果 = -1\n$反查细分成功 = -2");
        pure.AppendLine($"$native_result = 记录最近出闪检测({dex})\n{changes}");
        if (wrapper is null)
            pure.AppendLine($"$native_result = 记录目标出闪预校准({stage})\nIF $native_result != {(save ? 1 : 0)}\n    PRINT ASSERT_FAIL:{name}\n    RETURN\nENDIF");
        else pure.AppendLine($"CALL 离线{wrapper}");
        pure.AppendLine($"IF $Seed累计修正索引 != -7 or $消耗帧实际执行修正量 != 23\n    PRINT ASSERT_FAIL:offset-mutated-{name}\n    RETURN\nENDIF");
        output.Expected[name] = save;
        checks++;
    }
    Case("battle-target", 0, true);
    Case("battle-static-no-name", 0, true, "$野生获取结果_图鉴编号 = 0");
    Case("battle-mutable-target", 0, true, $"$目标全国图鉴编号 = {dex + 1}");
    Case("battle-no-shiny", 0, false, "$最近出闪检测结果 = 0");
    Case("battle-non-target", 0, false, $"$最近出闪检测图鉴编号 = {dex + 1}");
    Case("battle-conflicting-species", 0, false, $"$野生获取结果_图鉴编号 = {dex + 1}");
    Case("battle-recognition-failed", 0, false, "$野生获取结果_识图失败 = 1");
    Case("battle-before-calibration", 0, false, "$循环计数 = 0");
    Case("battle-disabled", 0, false, "$更新预校准 = 0");
    Case("battle-item-mode", 0, false, "$道具乱数模式 = 1");
    Case("battle-cleared-evidence", 0, false, "CALL 清空最近出闪检测");
    Case("summary-target", 1, true);
    Case("summary-gift", 1, true, "$野生获取结果_图鉴编号 = 0");
    Case("summary-non-target", 1, false, $"$目标全国图鉴编号 = {dex + 1}");
    Case("summary-species-not-hit", 1, false, "$本轮物种命中 = 0");
    Case("summary-conflicting-species", 1, false, $"$野生获取结果_图鉴编号 = {dex + 1}");
    Case("summary-recognition-failed", 1, false, "$野生获取结果_识图失败 = 1");
    Case("summary-before-calibration", 1, false, "$循环计数 = 0");
    Case("summary-disabled", 1, false, "$更新预校准 = 0");
    Case("summary-item-mode", 1, false, "$道具乱数模式 = 1");
    Case("unknown-source", 2, false);
    Case("battle-terminal-hook", 0, true, wrapper: "目标获取终止");
    Case("battle-nonterminal", 0, false, "$本轮流程结果 = 0", "目标获取终止");
    Case("summary-terminal-hook", 1, true, wrapper: "能力页终止");
    Case("summary-nonterminal", 1, false, "$反查细分成功 = 1", "能力页终止");
    pure.AppendLine("PRINT NATIVE_PRECALIBRATION_PASS");
    var compilation = Compilation.Create(SyntaxTree.Parse(pure.ToString()));
    var diagnostics = compilation.Compile(null).Where(d => d.IsError).ToArray();
    foreach (var d in diagnostics) Console.WriteLine($"Pure check {d.Location.StartLine + 1}: {d.Message}");
    if (diagnostics.Length != 0) return 1;
    if (compilation.KeyAction || compilation.NeedIL) throw new Exception("Pure tests must never use hardware, image labels, or real buttons.");
    using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(30));
    compilation.Evaluate(output, null, null, ImmutableDictionary<string, Func<int>>.Empty, timeout.Token);
    if (!output.Passed || output.Failed || output.Expected.Any(p => output.Markers.GetValueOrDefault(p.Key)?.Count != (p.Value ? 1 : 0)))
        throw new Exception("Native return value, writeback count, or assertions failed.");
    reports.Add(new { project = path, cases = output.Expected.Select(p => new { name = p.Key, save = p.Value, markers = output.Markers.GetValueOrDefault(p.Key) }) });
}
using (var file = new FileStream(Path.GetFullPath(args[0]), FileMode.CreateNew))
    JsonSerializer.Serialize(file, new { hardware_access = false, checks, projects = reports }, new JsonSerializerOptions { WriteIndented = true });
Console.WriteLine($"Native target-shiny writeback checks: {checks}; hardware=false");
return 0;

sealed class CheckOutput : IOutputAdapter
{
    public bool Passed { get; private set; }
    public bool Failed { get; private set; }
    public Dictionary<string, bool> Expected { get; } = new();
    public Dictionary<string, List<string>> Markers { get; } = new();
    private string current = "";
    public void Print(string message, bool newline)
    {
        if (message.StartsWith("CASE:")) { current = message[5..]; Markers[current] = new(); }
        if (message.StartsWith("PRECALIBRATION_UPDATE|")) Markers[current].Add(message);
        if (message.Contains("ASSERT_FAIL")) { Failed = true; Console.WriteLine(message); }
        if (message.Contains("NATIVE_PRECALIBRATION_PASS")) Passed = true;
    }
    public void Alert(string message) => throw new Exception(message);
}
