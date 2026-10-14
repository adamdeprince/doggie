# Silkie project conventions

- The main integration branch is `silkie`. Use it as the base for this project's
  work; `master` and `hdr-old` are not the main branch.
- The project website and user-facing HTML documentation belong in the top-level
  `html/` directory. `html/index.html` introduces the terminal emulator, features,
  installation, and documentation; `html/reference.html` is the extension reference.
  Do not leave the reference
  in an agent worktree or present a `.claude/` path to users.
- Document Silkie's extensions, configuration, and tools. Link inherited
  behavior to https://sw.kovidgoyal.net/kitty/ instead of duplicating kitty's docs.
- Explain that Silkie forks kitty, kitty extends traditional terminal protocols,
  and kittens are kitty's tools/plugins. Link the upstream kitten and protocol
  manuals and the HTML source browser at
  https://github.com/adamdeprince/silkie/tree/silkie for developers and LLMs.
- The reference sources are in `docs/silkie/`. Build them with `make html`.
  Keep the shared Goblin Core palette and the formal technical-document layout.

- Follow `/Users/adam/AGENTS.md` on this machine. Avoid arbitrary limits and
  fixed-size buffers where growing or input-sized storage works. A feature
  that stops working after a little use is broken; verify sustained use.
