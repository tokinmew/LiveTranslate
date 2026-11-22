# Windows development and test PC

Local inventory, November 21, 2026. These measurements describe one PC. Device enumeration opened no recording or playback stream.

| Item | Observed |
| --- | --- |
| OS | Windows x64, NT 10.0 build 26200 |
| CPU | Intel Core i7-13700F, 16 logical processors visible to the test process |
| RAM | 31.9 GiB physical |
| GPU | NVIDIA GeForce RTX 4070 Ti, 12,282 MiB total VRAM, 7,169 MiB free at sampling |
| Disk | About 1.24 TiB free on the system volume at sampling |
| Audio | WASAPI listed six render endpoints, six matching loopback endpoints and five microphone or virtual input endpoints. Device names and IDs are omitted. |
| Runtime | The prepared app's embedded Python is x64 3.13.17. The x64 .NET Framework C# compiler is installed. Build.cmd uses that compiler. |
| Development tools | Git 2.56.0.windows.4. The dotnet host was present. Its SDK listing returned no entries in this session. |
| Local source control | The original workspace had no Git metadata at its root. The GitHub CLI was absent from PATH and its standard install location at inspection. |
| GitHub | The connected account is **tokinmew**. Both visible repositories belonged to other apps. The available account connection supported neither repository creation nor release publication. Windows denied the credential manager's account-list request. Private LiveTranslate repository publication was pending at inspection. |

Start with the bundled CPU models and the default playback endpoint. This avoids a GPU download and provides a baseline for comparison. If a game and its chat use different endpoints, check both before estimating recognition accuracy. VRAM availability changes while a game is running. Compare measured game frame time, caption delay and missed utterances under the same game workload before selecting larger models.
