"""Resume narrowly identified, interrupted official Neutron migrations."""
import configparser
import sys

import sqlalchemy as sa

config = configparser.ConfigParser(interpolation=None)
config.read('/etc/neutron/neutron.conf')
engine = sa.create_engine(config['database']['connection'])
with engine.connect() as connection:
    inspector = sa.inspect(connection)
    columns = {c['name'] for c in inspector.get_columns('quotas')}
    print('Quota column state:', sorted(columns), flush=True)
    target = None
    if 'tenant_id' in columns and 'project_id' not in columns:
        target = '7d9d8eeec6ad'
    else:
        assert 'project_id' in columns, 'Unexpected quotas schema; refusing migration'
        address_columns = {c['name'] for c in inspector.get_columns('address_groups')}
        print('Address-group column state:', sorted(address_columns), flush=True)
        if {'standard_attr_id', 'description'} <= address_columns:
            # Replaying record creation is safe only for this empty lab table.
            assert connection.execute(sa.text('SELECT COUNT(*) FROM address_groups')).scalar_one() == 0, 'Address groups exist; refusing automatic replay'
            target = '26d1e9f5c766'
engine.dispose()
if target:
    # MySQL committed this DDL before the interrupted revision was recorded.
    # Make only this already-completed operation idempotent; run the remaining
    # official migration and version bookkeeping normally.
    from alembic import op
    from neutron.db.migration import cli

    original_drop_column = op.drop_column
    original_add_column = op.add_column
    original_create_foreign_key = op.create_foreign_key

    def add_column(table_name, column, *args, **kwargs):
        if (table_name, column.name) == ('address_groups', 'standard_attr_id'):
            existing = {c['name']: c for c in sa.inspect(op.get_bind()).get_columns(table_name)}
            if column.name in existing:
                assert isinstance(existing[column.name]['type'], sa.BigInteger), 'Unexpected existing column type'
                print('address_groups.standard_attr_id already exists; preserving completed DDL', flush=True)
                return
        return original_add_column(table_name, column, *args, **kwargs)

    def create_foreign_key(constraint_name, source_table, referent_table, local_cols, remote_cols, **kwargs):
        if source_table == 'address_groups' and local_cols == ['standard_attr_id']:
            for foreign_key in sa.inspect(op.get_bind()).get_foreign_keys(source_table):
                if foreign_key['constrained_columns'] == local_cols:
                    assert foreign_key['referred_table'] == referent_table and foreign_key['referred_columns'] == remote_cols
                    assert foreign_key.get('options', {}).get('ondelete') == kwargs.get('ondelete')
                    print('Address-group foreign key already exists; preserving completed DDL', flush=True)
                    return
        return original_create_foreign_key(constraint_name, source_table, referent_table, local_cols, remote_cols, **kwargs)

    def drop_column(table_name, column_name, *args, **kwargs):
        if (table_name, column_name) == ('networks', 'mtu'):
            columns_now = {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table_name)}
            if column_name not in columns_now:
                print('networks.mtu is already absent; preserving completed DDL', flush=True)
                return
        return original_drop_column(table_name, column_name, *args, **kwargs)

    op.drop_column = drop_column
    op.add_column = add_column
    op.create_foreign_key = create_foreign_key
    sys.argv = [
        'neutron-db-manage', '--config-file', '/etc/neutron/neutron.conf',
        '--config-file', '/etc/neutron/plugins/ml2/ml2_conf.ini',
        '--subproject', 'neutron', 'upgrade', target,
    ]
    cli.main()
else:
    print('Known interrupted migrations already completed', flush=True)
