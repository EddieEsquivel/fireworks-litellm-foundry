# Claude Desktop screenshots

Five authentic screenshots were supplied by the user on October 29, 2026, from macOS Claude Desktop. They are embedded at the corresponding steps in the main [README](../../README.md). The exact app and OS build numbers were not recorded; UI availability can vary by version and organization policy.

## Included captures

- `01-enable-developer-mode.png`: Help → Troubleshooting → Enable Developer Mode. Cropped to the relevant menus; unrelated menu-bar icons and the personal greeting are removed/redacted.
- `02-open-third-party-inference.png`: Developer → Configure Third-Party Inference.
- `03-gateway-connection.png`: Gateway connection, Static API key credential kind, and bearer auth. The operator's local gateway URL and the masked credential field are replaced with opaque explanatory labels baked into the image. Users must enter their own local values, not those labels.
- `04-model-routes.png`: Expanded `claude-opus-foundry` entry with tier alias and default toggle. Client capability hints and effort selections are the contributor's configuration, not a compatibility guarantee or a statement that the upstream is Anthropic Claude.
- `05-model-picker-and-test.png`: A harmless test conversation with `claude-opus-foundry` selected and a model response visible. This demonstrates the client UI; upstream routing must separately be verified through proxy requests and Foundry usage.

These are real UI captures with publication redactions, not synthetic mockups. The exported PNGs do not retain the original metadata. No API key, customer Foundry endpoint, or private Azure deployment identifier is included in the screenshots.

## Replacing or adding captures

Use a disposable conversation. Remove account names, email addresses, customer endpoints, keys, private workspace paths, billing information, and unrelated history. Use opaque redaction baked into pixels—not blur or removable overlays—and inspect the exported image before publishing. Never capture `runtime.py desktop-values --show-key` output. Include app version, OS version, and capture date with future replacements when available.
