# Runner isolation

Booting a mod set runs **arbitrary code** (PROJECT.md §8), so the runner confines
each container.

## Applied by default (itzg image)

Every boot (`build_run_args`) runs with:

- `--cap-drop ALL` then re-adds only the capabilities the entrypoint needs to fix
  permissions and drop to its unprivileged user (`CHOWN`, `DAC_OVERRIDE`,
  `FOWNER`, `SETGID`, `SETUID`, `KILL`).
- `--security-opt no-new-privileges`
- `--pids-limit 512` and `--memory` (per request)
- a throwaway container (`docker rm -f` in `finally`) and a hard boot timeout

The default still uses bridge networking because `itzg/minecraft-server`
downloads the Fabric server on first boot.

## Full network isolation (`--network none`)

For the strongest confinement, use the pre-baked offline image, which contains
the Fabric + vanilla server and libraries so no download is needed at boot:

```bash
docker build -f docker/Dockerfile.offline -t emendator/fabric-server:1.21.1 .
```

Then run the boot with `network="none"` (and point `_IMAGE` at
`emendator/fabric-server`). The version-specific args (loader / installer) are
build args in the Dockerfile; bump them per profile.

> The build "warms" the install by launching the server once to pull the vanilla
> jar and libraries, then bakes them in. Rebuild when changing the MC/loader
> version.
