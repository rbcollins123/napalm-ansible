from __future__ import print_function, unicode_literals

import os.path
import time

from ansible.module_utils.basic import AnsibleModule


# FIX for Ansible 2.8 moving this function and making it private
# greatly simplified for napalm-ansible's use
def return_values(obj):
    """Return native stringified values from datastructures.

    For use with removing sensitive values pre-jsonification."""
    yield str(obj)


DOCUMENTATION = """
---
module: napalm_install_config_confirm
author: "Richard Collins (@rbcollins123)"
version_added: "4.5"
short_description: "Installs the configuration taken from a file on a device supported
 by NAPALM with a revert_in timer, then attemps to confirm the configuration session
 within the target timer"
description:
    - "This library will take the configuration from a file and load it into a device
     running any OS supported by napalm. The old configuration will be replaced or
     merged with the new one.  The target device configuration session will be created
     with a commit confirmation timer to auto-revert the new configuration unless
     confirmed within the target # of seconds specififed in the revert_in argument.
     Ensure that the undelying napalm device driver you are using supports the
     commit-confirm feature per
     https://napalm.readthedocs.io/en/latest/support/index.html
    "
requirements:
    - napalm
options:
    hostname:
        description:
          - IP or FQDN of the device you want to connect to
        required: False
    username:
        description:
          - Username
        required: False
    password:
        description:
          - Password
        required: False
    provider:
        description:
          - Dictionary which acts as a collection of arguments used to define the characteristics
            of how to connect to the device. Connection arguments can be inferred from inventory
            and CLI arguments or specified in a provider or specified individually.
        required: False
    dev_os:
        description:
          - OS of the device
        required: False
    timeout:
        description:
          - Time in seconds to wait for the device to respond
        required: False
        default: 60
    optional_args:
        description:
          - Dictionary of additional arguments passed to underlying driver
        required: False
        default: None
    config_file:
        description:
          - Path to the file to load the configuration from. Either config or config_file is needed.
        required: False
    config:
        description:
          - Configuration to load. Either config or config_file is needed.
        required: False
    commit_changes:
        description:
          - If set to True the configuration will be actually merged or replaced. If the set to
            False, we will not apply the changes, just check and report the diff
        choices: [true,false]
        required: True
    replace_config:
        description:
          - If set to True, the entire configuration on the device will be replaced during the
            commit. If set to False, we will merge the new config with the existing one.
        choices: [true,false]
        default: False
        required: False
    diff_file:
        description:
          - A path to the file where we store the "diff" between the running configuration and the
            new configuration. If not set the diff between configurations will not be saved.
        default: None
        required: False
    get_diffs:
        description:
            - Set to False to not have any diffs generated. Useful if platform does not support
              commands being used to generate diffs. Note- By default diffs are generated even
              if the diff_file param is not set.
        choices: [true,false]
        default: True
        required: False
    archive_file:
        description: >
            File to store backup of running-configuration from device.
            Configuration will not be retrieved if not set.
        default: None
        required: False
    candidate_file:
        description: Store a backup of candidate config from device prior to a commit.
        default: None
        required: False
    revert_in:
        description: >
            The number of seconds that the device configuration session should
             automatically roll back to the previous configuration if the session is not
             confirmed.
        default: None
        required: True
    auto_confirm_time:
        description: >
            The number of seconds Ansible should wait before confirming the new
            configuration session on the target device.  This must be < revert_in for
            the session to actually be confirmed.  This can be used if you want to
            wait for network convergence or other propagations before cancelling the
            auto-reversion provided by the configuration session. The default is to auto confirm
            immediately.
        default: 0
        required: False
"""

EXAMPLES = """
- assemble:
    src: '../compiled/{{ inventory_hostname }}/'
    dest: '../compiled/{{ inventory_hostname }}/running.conf'

- name: Install Config with 120 second auto-rollback timer
  napalm_install_config_confirm:
    hostname: '{{ inventory_hostname }}'
    username: '{{ user }}'
    dev_os: '{{ os }}'
    password: '{{ passwd }}'
    config_file: '../compiled/{{ inventory_hostname }}/running.conf'
    commit_changes: '{{ commit_changes }}'
    replace_config: '{{ replace_config }}'
    get_diffs: True
    diff_file: '../compiled/{{ inventory_hostname }}/diff'
    revert_in: 300
    auto_confirm_time: 10
"""

RETURN = """
changed:
    description: whether the config on the device was changed
    returned: always
    type: bool
    sample: True
diff:
    description: diff of the change
    returned: always
    type: dict
    sample: {
        'prepared': "[edit system]\n-  host-name lab-testing;\n+  host-name lab;",
    }
"""

napalm_found = False
try:
    from napalm import get_network_driver
    from napalm.base import ModuleImportError

    napalm_found = True
except ImportError:
    pass


def save_to_file(content, filename):
    with open(filename, "w") as f:
        f.write(content)


def main():
    module = AnsibleModule(
        argument_spec=dict(
            hostname=dict(type="str", required=False, aliases=["host"]),
            username=dict(type="str", required=False),
            password=dict(type="str", required=False, no_log=True),
            provider=dict(type="dict", required=False),
            timeout=dict(type="int", required=False, default=60),
            optional_args=dict(required=False, type="dict", default=None),
            config_file=dict(type="str", required=False), config=dict(type="str", required=False),
            dev_os=dict(type="str", required=False),
            commit_changes=dict(type="bool", required=True),
            replace_config=dict(type="bool", required=False, default=False),
            diff_file=dict(type="str", required=False, default=None),
            get_diffs=dict(type="bool", required=False, default=True),
            archive_file=dict(type="str", required=False, default=None),
            candidate_file=dict(type="str", required=False, default=None),
            revert_in=dict(type="int", required=True),
            auto_confirm_time=dict(type="int", required=False, default=0)
        ), supports_check_mode=True, )

    if not napalm_found:
        module.fail_json(msg="the python module napalm is required")

    provider = module.params["provider"] or {}

    no_log = ["password", "secret"]
    for param in no_log:
        if provider.get(param):
            module.no_log_values.update(return_values(provider[param]))
        if provider.get("optional_args") and provider["optional_args"].get(param):
            module.no_log_values.update(
                return_values(provider["optional_args"].get(param))
            )
        if module.params.get("optional_args") and module.params["optional_args"].get(
                param
        ):
            module.no_log_values.update(
                return_values(module.params["optional_args"].get(param))
            )

    # allow host or hostname
    provider["hostname"] = provider.get("hostname", None) or provider.get("host", None)
    # allow local params to override provider
    for param, pvalue in provider.items():
        if module.params.get(param) is not False:
            module.params[param] = module.params.get(param) or pvalue

    hostname = module.params["hostname"]
    username = module.params["username"]
    dev_os = module.params["dev_os"]
    password = module.params["password"]
    timeout = module.params["timeout"]
    config_file = module.params["config_file"]
    config = module.params["config"]
    commit_changes = module.params["commit_changes"]
    replace_config = module.params["replace_config"]
    diff_file = module.params["diff_file"]
    get_diffs = module.params["get_diffs"]
    archive_file = module.params["archive_file"]
    candidate_file = module.params["candidate_file"]
    revert_in = module.params["revert_in"]
    auto_confirm_time = module.params["auto_confirm_time"]
    if config_file:
        config_file = os.path.expanduser(os.path.expandvars(config_file))
    if diff_file:
        diff_file = os.path.expanduser(os.path.expandvars(diff_file))
    if archive_file:
        archive_file = os.path.expanduser(os.path.expandvars(archive_file))
    if candidate_file:
        candidate_file = os.path.expanduser(os.path.expandvars(candidate_file))

    argument_check = {"hostname": hostname, "username": username, "dev_os": dev_os}
    for key, val in argument_check.items():
        if val is None:
            module.fail_json(msg=str(key) + " is required")

    if module.params["optional_args"] is None:
        optional_args = {}
    else:
        optional_args = module.params["optional_args"]

    try:
        network_driver = get_network_driver(dev_os)
    except ModuleImportError as e:
        module.fail_json(msg="Failed to import napalm driver: " + str(e))

    try:
        device = network_driver(
            hostname=hostname, username=username, password=password, timeout=timeout,
            optional_args=optional_args, )
        device.open()
    except Exception as e:
        module.fail_json(msg="cannot connect to device: " + str(e))

    try:
        if archive_file is not None:
            running_config = device.get_config(retrieve="running")["running"]
            save_to_file(running_config, archive_file)
    except Exception as e:
        module.fail_json(msg="cannot retrieve running config:" + str(e))

    try:
        if replace_config and config_file:
            device.load_replace_candidate(filename=config_file)
        elif replace_config and config:
            device.load_replace_candidate(config=config)
        elif not replace_config and config_file:
            device.load_merge_candidate(filename=config_file)
        elif not replace_config and config:
            device.load_merge_candidate(config=config)
        else:
            module.fail_json(msg="You have to specify either config or config_file")
    except Exception as e:
        module.fail_json(msg="cannot load config: " + str(e))

    try:
        if get_diffs:
            diff = device.compare_config()
            changed = len(diff) > 0
        else:
            changed = True
            diff = None
        if diff_file is not None and get_diffs:
            save_to_file(diff, diff_file)
    except Exception as e:
        module.fail_json(msg="cannot diff config: " + str(e))

    try:
        if candidate_file is not None:
            running_config = device.get_config(retrieve="candidate")["candidate"]
            save_to_file(running_config, candidate_file)
    except Exception as e:
        module.fail_json(msg="cannot retrieve running config:" + str(e))

    try:
        if module.check_mode or not commit_changes:
            device.discard_config()
        else:
            if changed:
                device.commit_config(revert_in=revert_in)
                time.sleep(auto_confirm_time)
                device.confirm_commit()
    except Exception as e:
        module.fail_json(msg="cannot install config: " + str(e))

    try:
        device.close()
    except Exception as e:
        module.fail_json(msg="cannot close device connection: " + str(e))

    module.exit_json(changed=changed, diff={"prepared": diff}, msg=diff)


if __name__ == "__main__":
    main()
