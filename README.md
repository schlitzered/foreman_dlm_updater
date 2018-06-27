Introduction
************
ForemanDlmUpdater is a Linux client counterpart to the awesome Foreman DLM Plugin,
that can be used coordinate the upgrade process of Linux/Unix systems.

ForemanDlmUpdater itself will not update your boxes, but it will call a series of scripts,
that will do the work. So this tool only implements the workflow how systems are updated.

The work flow is as follows:

1: the foreman_dlm_updater (the script) script gets called, for example via cron, or a systemd timer

2: the script will execute all scripts in the "needs_update.d" directory.

here you can place scripts, that check if updates are available for your system.

if any of the scripts has a non zero exit code, it is assumed that updates are available.
if no scripts are found, or all scripts have an return code of zero,
it is assumed that no updates are available, and the script will exit.

3: the script will try to acquire the lock from the "lock_name" config option.

if some other host is holding the look, the script will sleep for 60 seconds and try again
if the lock was acquired, the next step starts.
if there has been an error getting the lock, the script exits.

4: the script will execute all scripts in the "pre_update.d" directory.

here you can place scripts, that for example gracefully shut down databases.

if any of the scripts has a non zero exit code, it is assumed that something failed,
the script will exit, not releasing the lock. this protects other systems with the same lock_name to fail.
if all scripts returned with zero, the next step starts.


5: the script will execute all scripts in the "update.d" directory.

scripts placed here are executed, in order to install package updates.

if any of the scripts has a non zero exit code, it is assumed that something failed,
the script will exit, not releasing the lock. this protects other systems with the same lock_name to fail.
if all scripts returned with zero, the next step starts.

6: the script will execute all scripts in the "needs_reboot.d" directory.

scripts placed here are executed, in order to check if a system reboot is needed.

if any of the scripts has a non zero exit code, it is assumed that a reboot is needed,
this will execute the command specified in the "reboot_cmd" option
if all scripts returned with zero, it is assumed no reboot is needed
if there are no scripts, the reboot command will always be executed.

6 and a half: you need to make sure that the update script will be executed once by systemd, or your init system.
otherwise step 7 will only be executed if the next cron or systemd timer run of the script is triggered.

7: the script will execute all scripts in the "post_update.d" directory.

here you can place scripts, that for example restart databases, and check for there integrity.

if any of the scripts has a non zero exit code, it is assumed that something failed,
the script will exit, not releasing the lock. this protects other systems with the same lock_name to fail.
if all scripts returned with zero, the next step starts

8: finally the lock will be released, allowing other systems using the same lock_name to upgrade.


Installing
----------

pip install foreman-dlm-updater

the configuration is expected to be placed in /etc/foreman_dlm_updater/config.ini

an example configuration looks like this

```

[main]
log = /var/log/foreman_dlm_updater.log
logretention = 7
loglevel = DEBUG

# prevents the script from running twice on the same host
lock = /etc/foreman_dlm_updater/file.lock

# this file keeps the state of the script (what is the next task to be executed)
state = /etc/foreman_dlm_updater/state

# the dlm lock that will be acquired
lock_name = this_is_the_lock_name
foreman_url = https://foreman.example.com

client_crt = /etc/puppetlabs/puppet/ssl/certs/host.example.com.pem
client_key = /etc/puppetlabs/puppet/ssl/private_keys/host.example.com.pem
ca = /etc/ipa/ca.crt

needs_update.d = /etc/foreman_dlm_updater/needs_update.d/
pre_update.d = /etc/foreman_dlm_updater/pre_update.d/
post_update.d = /etc/foreman_dlm_updater/post_update.d/
needs_reboot.d = /etc/foreman_dlm_updater/needs_reboot.d/
update.d = /etc/foreman_dlm_updater/update.d/
reboot_cmd = /usr/sbin/reboot

```


Author
------

Stephan Schultchen <stephan.schultchen@gmail.com>

License
-------

Unless stated otherwise on-file foreman-dlm-updater uses the MIT license,
check LICENSE file.

Contributing
------------

If you'd like to contribute, fork the project, make a patch and send a pull
request.