import sqlite3; conn=sqlite3.connect('restarentai.db'); c=conn.cursor(); c.execute('SELECT id, name FROM restaurants'); print(c.fetchall())
