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
foreach (var language in new[] { 0, 1 })
{
    var variant = Regex.Replace(source, @"^\$测试ROM语言 = [01]", $"$测试ROM语言 = {language}", RegexOptions.Multiline);
    var variantErrors = Compilation.Create(SyntaxTree.Parse(variant)).Compile(labels).Where(d => d.IsError).ToArray();
    foreach (var d in variantErrors) Console.WriteLine($"ROM={language}, {d.Location.StartLine + 1}: {d.Message}");
    if (variantErrors.Length != 0) return 1;
    Console.WriteLine($"1.6.4-a ROM={language} full compilation: errors=0");
}

string Function(string name)
{
    var match = Regex.Match(source, "^FUNC " + Regex.Escape(name) + @"\([^\r\n]*\)\s*:\s*INT\r?\n.*?^ENDFUNC\s*$",
        RegexOptions.Multiline | RegexOptions.Singleline);
    if (!match.Success) throw new Exception($"Missing actual test function: {name}");
    return match.Value + "\n";
}
string Procedure(string name)
{
    var match = Regex.Match(source, "^FUNC " + Regex.Escape(name) + @"\r?\n.*?^ENDFUNC\r?$",
        RegexOptions.Multiline | RegexOptions.Singleline);
    if (!match.Success) throw new Exception($"Missing actual test procedure: {name}");
    return match.Value + "\n";
}
string OfflineCreation(string procedure)
{
    var instrumented = new StringBuilder();
    foreach (var line in procedure.Split('\n'))
    {
        var statement = line.Trim();
        if (Regex.IsMatch(statement, @"^(?:[ABX](?: DOWN| UP)?|LS (?:DOWN|UP|LEFT|RIGHT|RESET))$"))
            instrumented.AppendLine($"    PRINT \"NATIVE_CREATE|CASE=\" & $native_case & \"|EVENT=KEY|VALUE={statement}\"");
        else if (statement.StartsWith("WAIT "))
        {
            instrumented.AppendLine($"    $native_wait_value = {statement[5..]}");
            instrumented.AppendLine("    PRINT \"NATIVE_CREATE|CASE=\" & $native_case & \"|EVENT=WAIT|VALUE=\" & $native_wait_value");
        }
        else instrumented.AppendLine(line.TrimEnd('\r'));
    }
    return instrumented.ToString();
}
var pure = new StringBuilder("$native_result = 0\n$测试OP修正次数 = 0\n$测试OP修正上限 = 10\n$测试OP修正MS = 0\n");
pure.AppendLine("$测试ROM语言 = 0\n$测试主角性别 = 0\n$测试确认索引 = 0\n$测试开场等待MS = 0\n$native_case = \"\"\n$native_wait_value = 0");
pure.AppendLine("$测试FAST分 = 0\n$测试MID分 = 0\n$测试SLOW分 = 0\n$测试语速状态 = -1");
var openingAWaits = Regex.Match(source, @"^\$测试开场A等待 = \[[^\r\n]+\]", RegexOptions.Multiline);
if (!openingAWaits.Success) throw new Exception("Missing actual opening A wait table.");
pure.AppendLine(openingAWaits.Value);
pure.Append(Function("测试_判定存档状态"));
pure.Append(Function("测试_判定语速"));
pure.Append(Function("测试_增加OP等待"));
var creation = Procedure("测试_创建新游戏");
if (creation.Contains("$测试ROM语言")) throw new Exception("ROM language must not change creation actions.");
pure.Append(OfflineCreation(creation));
// Preserve the actual label dispatch, supplying distinct offline scores for each language.
var reading = Procedure("测试_读取语速")
    .Replace("@日版TEXT_SPEED_FAST", "94").Replace("@日版TEXT_SPEED_MID", "96").Replace("@日版TEXT_SPEED_SLOW", "92")
    .Replace("@TEXT_SPEED_FAST", "98").Replace("@TEXT_SPEED_MID", "60").Replace("@TEXT_SPEED_SLOW", "61");
pure.Append(reading);
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
var dialogue = Regex.Match(source,
    @"^    PRINT 【创建进度】推进开场说明与大木博士对话\r?\n    (FOR 35\r?\n        B\r?\n        WAIT 800\r?\n    NEXT)\r?\n",
    RegexOptions.Multiline);
if (!dialogue.Success) throw new Exception("The actual user-tested Oak dialogue must use FOR 35, B, WAIT 800, NEXT.");
// Execute the actual loop with key/WAIT statements replaced by counters only.
var offlineDialogue = dialogue.Groups[1].Value.Replace("        B\r\n", "        $native_b_count += 1\r\n")
    .Replace("        B\n", "        $native_b_count += 1\n")
    .Replace("        WAIT 800", "        $native_b_wait += 800");
pure.AppendLine("$native_b_count = 0\n$native_b_wait = 0");
pure.AppendLine(offlineDialogue);
pure.AppendLine("IF $native_b_count != 35\n    PRINT ASSERT_FAIL:oak-b-count\n    RETURN\nENDIF");
pure.AppendLine("IF $native_b_wait != 28000\n    PRINT ASSERT_FAIL:oak-b-wait\n    RETURN\nENDIF");
checks += 2;
foreach (var language in new[] { 0, 1 })
{
    pure.AppendLine($"$测试ROM语言 = {language}\nCALL 测试_读取语速");
    AssertCall("$测试FAST分", language == 0 ? 98 : 94, $"text-fast-{language}");
    AssertCall("$测试MID分", language == 0 ? 60 : 96, $"text-mid-{language}");
    AssertCall("$测试SLOW分", language == 0 ? 61 : 92, $"text-slow-{language}");
    AssertCall("$测试语速状态", language == 0 ? 0 : 1, $"text-choice-{language}");
    foreach (var gender in new[] { 0, 1 })
    {
        var caseName = $"{(language == 0 ? "EN" : "JP")}_{(gender == 0 ? "MALE" : "FEMALE")}";
        pure.AppendLine($"$native_case = \"{caseName}\"\n$测试主角性别 = {gender}\nCALL 测试_创建新游戏");
    }
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
// Evaluate only arithmetic and instrumented procedures, never real keys, waits, or labels.
if (compilation.KeyAction || compilation.NeedIL) throw new Exception("Native test must not access hardware or labels.");
var output = new TestOutput();
using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(30));
compilation.Evaluate(output, null, null, ImmutableDictionary<string, Func<int>>.Empty, timeout.Token);
var sameActions = true;
foreach (var gender in new[] { "MALE", "FEMALE" })
{
    var match = output.CreationTraces.TryGetValue($"EN_{gender}", out var english)
        && output.CreationTraces.TryGetValue($"JP_{gender}", out var japanese)
        && english.Count > 0 && english.SequenceEqual(japanese);
    Console.WriteLine($"Creation trace ROM 0/1, {gender}: identical={match}");
    sameActions &= match;
    checks++;
}
var passed = output.Passed && !output.Failed && sameActions;
Console.WriteLine($"Native bootstrap decision/OP/dialogue/language checks: {checks}, pass={passed}");
return passed ? 0 : 1;

sealed class TestOutput : IOutputAdapter
{
    public bool Passed { get; private set; }
    public bool Failed { get; private set; }
    public Dictionary<string, List<string>> CreationTraces { get; } = new();
    public void Print(string message, bool newline)
    {
        if (message.Contains("ASSERT_FAIL")) { Failed = true; Console.WriteLine(message); }
        if (message.Contains("NATIVE_TID_BOOTSTRAP_PASS")) Passed = true;
        var trace = Regex.Match(message, @"^NATIVE_CREATE\|CASE=([A-Z_]+)\|EVENT=(KEY|WAIT)\|VALUE=(.*)$");
        if (trace.Success)
        {
            var key = trace.Groups[1].Value;
            if (!CreationTraces.TryGetValue(key, out var events)) CreationTraces[key] = events = new List<string>();
            events.Add(trace.Groups[2].Value + ":" + trace.Groups[3].Value);
        }
    }
    public void Alert(string message) => throw new Exception(message);
}
