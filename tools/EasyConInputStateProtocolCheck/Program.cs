using EasyDevice;
using System.Text.Json;

// Calls the production buffer/DTO, either linked from patched pinned source
// (CI) or from the actual published Device assembly (local delivery).
InputStateBuffer.Configure("protocol-run", "protocol-session", "protocol-stage", "device_report");
var results = new List<InputStateResponse>();
long previous = 0;
void Snapshot() {
    var state = InputStateBuffer.Read(previous, true);
    results.Add(state);
    previous = state.Sequence;
}
Snapshot();
foreach (var button in new[] {SwitchButton.A, SwitchButton.B, SwitchButton.A | SwitchButton.ZL}) {
    InputStateBuffer.Publish((ushort)button, (byte)SwitchHAT.CENTER, 0, 255, 255, 0);
    Snapshot();
}
foreach (var hat in Enum.GetValues<SwitchHAT>()) {
    InputStateBuffer.Publish(0, (byte)hat, 128, 128, 128, 128);
    Snapshot();
}
InputStateBuffer.Publish(0, (byte)SwitchHAT.CENTER, 128, 128, 128, 128);
Snapshot();
InputStateBuffer.SetConnection("error");
Snapshot();
InputStateBuffer.SetConnection("connected");
// Exercise a real history overflow response, not a hand-built ideal payload.
for (int i = 0; i < 600; ++i)
    InputStateBuffer.Publish((ushort)(i % 2 == 0 ? SwitchButton.A : 0), (byte)SwitchHAT.CENTER, 128,128,128,128);
Snapshot();
var json = JsonSerializer.Serialize(results);
if (args.Length > 0) File.WriteAllText(args[0], json);
else Console.WriteLine(json);
