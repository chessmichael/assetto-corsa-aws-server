# AssettoServer `extra_cfg.yml`

AssettoServer keeps its feature switches (AI traffic, weather plugins, voting,
etc.) in `cfg/extra_cfg.yml`. **You do not manage this file from the `ac` tool.**

AssettoServer **auto-creates it with sane defaults on first start**, and the
content sync is deliberately set up to *preserve* the server's own copy (the
`ac-presync` script excludes `extra_cfg.yml` from its `--delete` sync). So a
fresh deploy "just works" with stock features.

## Tweaking it later

To change advanced AssettoServer features, edit the file on the box. Easiest is
over SSM from your machine — for example to view it:

```
aws ssm send-command --instance-ids <id> \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["cat /opt/ac/server/cfg/extra_cfg.yml"]'
```

…or open an interactive session with `aws ssm start-session --target <id>`
(requires the Session Manager plugin) and edit it with `nano`, then
`ac restart`.

Wiring richer `extra_cfg.yml` management (AI traffic packs, dynamic weather)
into the wizard is a planned future enhancement — see the project README's
"Out of scope / later" section.
