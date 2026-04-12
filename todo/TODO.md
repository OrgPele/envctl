1. Create a wrapper for codex using tmux

2. auto commit and push when creating a PR - IN PROGRESS

3. Create smarter commit message system, rn we're using changelog for the commit message, which works fine - but I want tp abundon the changelog... Instead - I want to be using proprietry temp file that is never commited, every change the AI will make will be appended to that commit message file, and every time we will actually commit stuff from the CLI - the commit message will be from "### Envctl pointer ###" to the end of the file, we will be move the "### Envctl pointer ###" to the end of the file (we also need to edit the command installer to support it)

4. change current way we work - from now on we should be using global (per user) .gitignore to include MAIN_TASK.md and .envctl (and all other stuff we should not be having in the repo that envctl is using)
