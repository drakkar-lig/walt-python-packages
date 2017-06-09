
def stream_db_logs(db, logs_handler, **params):
    # ensure all past logs are commited
    db.commit()
    # let the logs handler start buffering realtime logs
    logs_handler.notify_history_processing_startup()
    db.commit()
    # create a server cursor
    cursor_name = db.create_server_cursor()
    # start streaming db logs
    for record in db.get_logs(cursor_name, **params):
        d = record._asdict()
        if logs_handler.write_to_client(
                    senders_filtered = True, **d) == False:
            break
    # delete server cursor
    db.delete_server_cursor(cursor_name)
    # notify history dump is complete
    logs_handler.notify_history_processed()

