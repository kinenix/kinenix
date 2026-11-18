"""Flow packages (.kinx): the publisher key, trusted publishers, and building a signed package.

Design: docs/design/flow-deploy.md, sections 4 and 5. Signing uses OpenSSH (`ssh-keygen -Y`), so Kinenix
needs no cryptography library of its own.
"""
