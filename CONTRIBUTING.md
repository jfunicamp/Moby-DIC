# Contributing to Moby-DIC

Thank you for your interest in Moby-DIC. Bug reports, questions, example datasets and code
contributions are welcome. *Contribuições em português também são bem-vindas — veja o fim do
arquivo.*

## Reporting a problem or asking a question

Open an [issue](https://github.com/jfunicamp/Moby-DIC/issues). For a bug, please include:

- the Moby-DIC version (`Moby-DIC --version`, or in the subtitle of the viewer) and how you run it
  (Windows executable or from source, operating system, Python version);
- what you did, what you expected and what happened (error message or screenshot);
- if possible, a few images or a short video that reproduce the problem, and the
  `parametros.json` of the result folder.

Questions about how to measure something (subset size, reference updating, synchronisation with
the test machine) are welcome as issues too; check the [documentation](docs/index.md) and the
[troubleshooting page](docs/troubleshooting.md) first.

## Development setup

```bash
git clone https://github.com/jfunicamp/Moby-DIC.git
cd Moby-DIC
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -r requirements-extra.txt   # Windows: .venv\Scripts\python
.venv/bin/python -m pytest -q tests
```

The tests use synthetic images with known displacement fields and finish in about two minutes.
`imageio-ffmpeg` (in `requirements-extra.txt`) is needed for the variable-frame-rate video test;
without it that test is skipped. The interface starts with `python -m mobydic`; the command-line
tools are described in [docs/command-line.md](docs/command-line.md).

## How changes are made

- **One issue per change.** Open (or comment on) an issue before starting, so the change has a
  public record and a place for discussion.
- **Small, focused commits** that reference the issue (`Refs #12`, or `Closes #12` in the last
  one). A commit should be readable on its own: one fix or one step of a feature.
- **Tests and documentation travel with the code.** New behaviour gets a test in `tests/`
  (synthetic data with a known answer whenever possible) and, when visible to users, an entry in
  [docs/changelog.md](docs/changelog.md) and in the relevant documentation page.
- **Continuous integration** runs the test suite on Linux and Windows for every push and pull
  request; keep it green.
- **Pull requests** are welcome from forks. Describe what changes and why, and link the issue.
- **Releases** bundle commits that are already on `main`: version number in `mobydic/__init__.py`,
  `pyproject.toml` and `CITATION.cff`, changelog, tag and the Windows executable.

### Code conventions

- Python 3.10+, NumPy/SciPy, compiled kernels with Numba. Keep the analysis reproducible: every
  parameter that affects the result is written to `parametros.json`.
- User-facing text exists in Portuguese and English (`mobydic/i18n.py`, the interface and the
  viewer); add both.
- Internal names and comments are mostly in Portuguese; either language is fine in new code.

## How Moby-DIC is developed (AI assistance)

Moby-DIC is maintained by João Felipe Queiroz Rodrigues. Much of the code, tests and
documentation was written with AI coding assistants (Anthropic Claude through Claude Code, and
OpenAI Codex for code review), under the maintainer's direction: the maintainer defines the
methods and requirements, reviews and validates every change against tests with known solutions
and real test data, and makes the design decisions. Contributions made with AI assistance are
welcome on the same terms; please say so in the pull request and make sure you understand and
have checked the code you submit.

## Code of conduct

Be respectful and constructive. Harassment or personal attacks are not accepted in issues, pull
requests or any other project space.

## License

By contributing, you agree that your contributions are licensed under the project's
[MIT License](LICENSE).

---

### Em português

Abra uma [issue](https://github.com/jfunicamp/Moby-DIC/issues) para relatar problemas, tirar
dúvidas ou propor mudanças (em português ou inglês). Para contribuir com código: uma issue por
mudança, commits pequenos que citem a issue (`Refs #12`), testes e documentação junto com o
código, e a integração contínua passando. O desenvolvimento usa assistentes de IA (Claude e
Codex) sob a direção e a revisão do mantenedor, como descrito acima.
