Show the token usage breakdown for the current Claude Code session.

Run the following command and display its output verbatim to the user:

```
python3 tokenmaxxer/cli.py
```

The output is a visual bar chart showing how much of the context window each component is consuming — including CLAUDE.md, memory files, custom skills, conversation history, tool outputs, and the Claude Code baseline overhead. Each row shows the component name, a proportional bar, percentage, and exact token count.

If the command fails, tell the user to run `python3 setup.py` first to configure the plugin, then try again.
