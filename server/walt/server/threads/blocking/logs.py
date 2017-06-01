
def stream_db_logs(db, logs_handler, cursor_name, **params):
    for record in db.get_logs(cursor_name, **params):
        d = record._asdict()
        if logs_handler.write_to_client(
                    senders_filtered = True, **d) == False:
            break
    db.delete_server_cursor(cursor_name)

