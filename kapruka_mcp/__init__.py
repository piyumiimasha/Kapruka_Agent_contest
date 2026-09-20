from pkgutil import extend_path


# Share this namespace with the installed MCP SDK.
__path__ = extend_path(__path__, __name__)
