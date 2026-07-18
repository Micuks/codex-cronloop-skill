# Security policy

Please report security issues privately through GitHub's **Report a vulnerability** flow instead of opening a public issue.

Cronloop runs monitoring commands and a foreground TTY sleep inside the current Codex task. Keep recovery authority narrow, validate process identity before restarting work, and never place passwords, API tokens, private keys, or credential-bearing URLs in the monitoring prompt.
