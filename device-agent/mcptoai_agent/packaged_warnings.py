"""Suppress only the known third-party Authlib warning in frozen builds.

Source installs and CI intentionally retain this warning for upgrade tracking.
"""


def configure_packaged_warnings():
    import sys
    import warnings

    if not getattr(sys, 'frozen', False):
        return
    warnings.filterwarnings(
        'ignore',
        message=r'^authlib\.jose module is deprecated, please use joserfc instead\.',
        category=DeprecationWarning,
        module=r'^fastmcp\.server\.auth\.(?:providers\.jwt|jwt_issuer)$',
    )
