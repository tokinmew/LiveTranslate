# LiveTranslate for Windows

See [the user guide](LiveTranslate/docs/README.md), [engineering notes](docs/ENGINEERING.md), and [owner and release instructions](docs/OWNER.md).

Application updates come only from published stable releases in the public [tokinmew/LiveTranslate repository](https://github.com/tokinmew/LiveTranslate/releases/latest). Users check and install them in **Settings → Updates**, without a GitHub sign-in. Source commits alone do not publish an app update: every release needs matching tagged source and update assets signed by the existing release key.

Run `LiveTranslate/scripts/Build.cmd` to compile the Windows interface. For the full portable app, run `tools/build_portable.py` with `--app LiveTranslate`, `--base` pointing to the original 0.6.7 Windows Test ZIP, and `--output` pointing to a new ZIP. The base supplies the checked offline runtime, licenses and models. Build the graphical installer from the resulting portable archive with `installer/desktop-setup/Build-DesktopSetup.ps1`.
