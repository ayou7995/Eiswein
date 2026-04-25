"""Service layer — orchestrates repositories + domain logic.

Services own cross-repository transactions and business rules that
don't fit in a single repository. They accept a SQLAlchemy ``Session``
(and any other collaborators) via constructor injection so tests can
wire in in-memory repos without monkeypatching module globals.
"""
