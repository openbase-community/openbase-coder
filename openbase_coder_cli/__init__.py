from openbase_coder_cli.plugins.site import activate_plugin_site

# Plugin packages live outside the (replaceable) standalone runtime package;
# expose them to every Openbase process, including entry-point discovery.
activate_plugin_site()
