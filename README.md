# LiveTranslate for Windows

See [the user guide](LiveTranslate/README.md), [engineering notes](docs/ENGINEERING.md), and [owner and release instructions](docs/OWNER.md).

Run LiveTranslate/Build.cmd to compile the interface. For the full portable app use tools/build_portable.py with --app LiveTranslate, --base pointing to the original 0.6.4 Windows ZIP and --output pointing to a new ZIP. The base supplies the checked offline runtime, licenses and models. Source alone does not install those files.
