"""Support empty tables created early by legacy application startup."""
from sqlalchemy import inspect, Column, Float, text, UniqueConstraint


def create_table_unless_matching(op,name,*columns,**kwargs):
    inspector=inspect(op.get_bind())
    if not inspector.has_table(name):
        return op.create_table(name,*columns,**kwargs)
    expected={c.name:c for c in columns if isinstance(c,Column)}
    actual={c['name']:c for c in inspector.get_columns(name)}
    if name=='execution_orders' and set(expected)-set(actual)=={'filled_base_fee'} and not set(actual)-set(expected):
        if op.get_bind().execute(text('SELECT COUNT(*) FROM execution_orders')).scalar():
            raise RuntimeError('An older execution ledger has orders; review base-fee accounting before migrating')
        op.add_column(name,Column('filled_base_fee',Float(),nullable=False,server_default='0'))
        actual={c['name']:c for c in inspect(op.get_bind()).get_columns(name)}
    if set(actual)!=set(expected):
        raise RuntimeError(f'Pre-existing {name} has unexpected columns; migration stopped')
    for key,column in expected.items():
        reflected=actual[key]
        if column.type._type_affinity is not reflected['type']._type_affinity or bool(column.nullable)!=bool(reflected['nullable']):
            raise RuntimeError(f'Pre-existing {name}.{key} does not match the migration schema')
    # Unique constraints/primary keys must also match before preserving existing tables.
    expected_pk={c.name for c in expected.values() if c.primary_key}
    if set(inspector.get_pk_constraint(name)['constrained_columns'])!=expected_pk:
        raise RuntimeError(f'Pre-existing {name} has a different primary key')
    unique_sets={tuple(c['column_names']) for c in inspector.get_unique_constraints(name)}
    unique_sets|={tuple(i['column_names']) for i in inspector.get_indexes(name) if i.get('unique')}
    if any((c.name,) not in unique_sets for c in expected.values() if c.unique):
        raise RuntimeError(f'Pre-existing {name} is missing a required unique constraint')
    expected_unique={
        tuple(constraint.columns.keys()) or tuple(str(column) for column in constraint._pending_colargs)
        for constraint in columns if isinstance(constraint,UniqueConstraint)
    }
    if not expected_unique.issubset(unique_sets):
        raise RuntimeError(f'Pre-existing {name} is missing a required unique constraint')
