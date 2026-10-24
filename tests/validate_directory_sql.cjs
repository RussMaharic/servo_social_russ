// Run with PGLITE_MODULE pointing to a separately installed pinned PGlite module.
// Uses an isolated embedded PostgreSQL instance, never the hosted database.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {PGlite}=require(process.env.PGLITE_MODULE||'@electric-sql/pglite');
(async()=>{
 const db=new PGlite();
 try{
  await db.exec('CREATE ROLE anon; CREATE ROLE authenticated; CREATE TABLE public.existing_app(value text); INSERT INTO public.existing_app VALUES (\'preserved\');');
  const migrations=fs.readdirSync(path.join(__dirname,'../supabase/migrations')).filter(x=>x.endsWith('_create_t2_directory.sql'));
  assert.equal(migrations.length,1);
  const sql=fs.readFileSync(path.join(__dirname,'../supabase/migrations',migrations[0]),'utf8');
  await db.exec(sql);await db.exec(sql); // Safe to run the setup again.
  assert.equal((await db.query('SELECT value FROM public.existing_app')).rows[0].value,'preserved');
  await db.exec('SET ROLE t2_directory_app; SET search_path TO t2_directory, pg_catalog;');
  const token='a'.repeat(64);
  await db.query('INSERT INTO devices VALUES ($1,$2,$3)',['device-owner','owner',token]);
  await db.query('INSERT INTO devices VALUES ($1,$2,$3)',['device-leader','leader',token]);
  await db.query('INSERT INTO followers(id,label,endpoint,certificate,seen,busy) VALUES ($1,$2,$3,$4,$5,$6)',
    ['device-owner','Desk follower','ws://127.0.0.1:8765','{}',100,0]);
  await db.exec('BEGIN');
  const row=(await db.query('SELECT * FROM followers WHERE id=$1 FOR UPDATE',['device-owner'])).rows[0];
  assert.equal(row.busy,0);
  await db.query('UPDATE followers SET holder=$1,held_until=$2 WHERE id=$3',['device-leader',145,'device-owner']);
  await db.exec('COMMIT');
  assert.equal((await db.query('SELECT holder FROM followers')).rows[0].holder,'device-leader');
  await assert.rejects(()=>db.query('DELETE FROM devices'),e=>e.code==='42501');
  await assert.rejects(()=>db.query('INSERT INTO devices VALUES ($1,$2,$3)',['another-device','owner',token]),e=>e.code==='23505');
  await db.exec('RESET ROLE; SET ROLE anon;');
  await assert.rejects(()=>db.query('SELECT * FROM t2_directory.devices'),e=>e.code==='42501');
  await db.exec('RESET ROLE; SET ROLE authenticated;');
  await assert.rejects(()=>db.query('SELECT * FROM t2_directory.followers'),e=>e.code==='42501');
  await db.exec('RESET ROLE');
  const security=(await db.query("SELECT relrowsecurity FROM pg_class JOIN pg_namespace ON pg_namespace.oid=relnamespace WHERE nspname='t2_directory' AND relname IN ('devices','followers')")).rows;
  assert.equal(security.length,2);assert.ok(security.every(x=>x.relrowsecurity));
  console.log('PostgreSQL migration, idempotence, parameter binding, row locking, uniqueness and private-role permissions passed.');
 }finally{await db.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
