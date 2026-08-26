"""Build-time feature profile.

Release artifacts keep dynamic csc/tool/Python execution out of the public MCP
surface. Developer builds must deliberately change this source constant and
still opt in through local policy; an environment variable cannot enable it.
"""

DEVELOPER_BUILD = False
