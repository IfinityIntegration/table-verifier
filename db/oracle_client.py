from db.base_client import BaseClient


class OracleClient(BaseClient):
    index_sql = """SELECT i.index_name, c.column_name, c.column_position
        FROM all_indexes i JOIN all_ind_columns c
          ON c.index_owner = i.owner AND c.index_name = i.index_name
        WHERE i.table_owner = :owner AND i.table_name = :table_name
          AND i.index_type = 'NORMAL' AND i.status = 'VALID'
          AND i.visibility = 'VISIBLE' AND c.descend = 'ASC'
        ORDER BY i.index_name, c.column_position"""
    side = 'Oracle'
    probe = 'SELECT 1 FROM DUAL'
    exists_sql = 'SELECT 1 FROM all_tables WHERE owner = :owner AND table_name = :table_name'
    columns_sql = """SELECT column_name, data_type, nullable, column_id
        FROM all_tab_columns WHERE owner = :owner AND table_name = :table_name
        ORDER BY column_id"""

    def _params(self, table):
        return {'owner': self.config['schema'], 'table_name': table}

    def _connect(self):
        import oracledb
        from decimal import Decimal
        cfg = self.config
        dsn = oracledb.makedsn(cfg['host'], cfg['port'], service_name=cfg['service_name'])
        connection = oracledb.connect(user=cfg['username'], password=cfg['password'], dsn=dsn,
                                     tcp_connect_timeout=15)
        def output_handler(cursor, metadata):
            if metadata.type_code == oracledb.DB_TYPE_NUMBER:
                return cursor.var(oracledb.DB_TYPE_VARCHAR, arraysize=cursor.arraysize,
                                  outconverter=Decimal)
        try:
            connection.outputtypehandler = output_handler
            with connection.cursor() as cursor:
                cursor.execute("ALTER SESSION SET NLS_NUMERIC_CHARACTERS = '.,'")
                cursor.execute('SET TRANSACTION READ ONLY')
        except Exception:
            connection.close()
            raise
        return connection
