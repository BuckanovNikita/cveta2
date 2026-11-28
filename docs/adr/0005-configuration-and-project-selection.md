# Keep personal credentials and cache paths separate from team project definitions

## Project selection

At the snapshot, select a project by numeric ID or name. Configuration commands can also use the project definition key. An organization prefix scopes a name to that workspace, and a leading slash selects the personal workspace. The global configuration path comes from the explicit option, then the environment, then the saved personal reference. [Project selection tests](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_org_resolution.py) · [Global file selection](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_config_global_selection.py)

## Configuration writes

`setup --global` writes team settings. Attaching a global file changes the personal reference. `--unset` removes a setting from its owning file, and `--list` shows its effective value and origin. Legacy migration previews how settings will be divided before activation. [Setup options](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_setup_options.py) · [Listing behavior](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_setup_list.py)

## Diagnostics

`doctor` checks required CVAT configuration without authenticating to CVAT. Optional checks report AWS credentials, ClearML connectivity and cache access separately. `doctor --cache` repairs permissions on owned paths and identifies paths requiring another owner. [CLI exit contract](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_review_interfaces.py) · [Permission checks](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_doctor_checks.py)

## Timeout warning

A nonnumeric `CVETA2_DATA_TIMEOUT` leaves the timeout unset. At this revision the warning includes the supplied value. [Pinned parser](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/cveta2/adapters/config/settings.py#L399) · [SIP-342](https://linear.app/sip-ds-team/issue/SIP-342/reconcile-timeout-diagnostics-with-the-input-redaction-adr)
