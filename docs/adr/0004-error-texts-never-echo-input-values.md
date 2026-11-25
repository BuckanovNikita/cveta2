# Error texts never echo input values, and URL credentials are refused fail-closed

Configuration files, `dataset.yaml`, source snapshots and command-line flags can carry secrets, mostly as URL userinfo (`s3://key:secret@host/...`) or tokens. Users paste error output into chats and issues. So a cveta2 error names where the problem is, such as a path, a field name, a line and column, or a row number, and never repeats the offending value. Diagnostics name an exception by its class only. A YAML syntax error is reported without the source line.

URL-typed values are refused when they may carry a login or password before the host (`has_url_userinfo`). The rule deliberately over-detects. It flags any `:` before the last `@`, because an AWS secret that contains `/` makes `urlsplit` end the authority early and miss the password. As a result, rare legitimate values such as `https://host:8080/a@b` are refused too.

Why: a false refusal costs the user one rename, while a missed credential ends up in logs, published `dataset.yaml` files and ClearML.

Consequence: error messages are less specific than they could be, and tests assert that the value is absent from the error, not only that the error is raised.
