import { MongoClient, type Collection, type Document, type Filter, type FindCursor, type WithId } from "mongodb";
import { Pool } from "pg";
import type { CleanupPorts, ExpiredMessage, ExpiredSession } from "./cleanup.ts";
import { FirebaseAuthClient } from "./firebase-auth.ts";

export interface HyperdriveBinding { connectionString: string }
export interface CleanupEnv {
  POSTGRES: HyperdriveBinding;
  FIREBASE_PROJECT_ID: string;
  FIREBASE_CREDENTIALS_BASE64: string;
  MONGODB_URI: string;
  MONGODB_DATABASE: string;
  MONGODB_SESSIONS_COLLECTION?: string;
  MONGODB_MESSAGES_COLLECTION?: string;
  QDRANT_URL: string;
  QDRANT_API_KEY: string;
  QDRANT_SUMMARIES_COLLECTION?: string;
}

function required(value: string | undefined, name: string): string {
  if (!value?.trim()) throw new Error(`missing_${name.toLowerCase()}`);
  return value.trim();
}

function expiredFilter(field: string, cutoff: Date): Document {
  return { [field]: { $type: "date", $lt: cutoff } };
}

function mongoDocuments<T extends Document>(
  collection: Collection<T>,
  filter: Document,
  projection: Document,
): FindCursor<WithId<T>> {
  return collection.find(filter as Filter<T>, { projection, maxTimeMS: 30_000 }).sort({ _id: 1 });
}

async function qdrantRequest<T>(env: CleanupEnv, path: string, body: object): Promise<T> {
  const base = required(env.QDRANT_URL, "QDRANT_URL").replace(/\/+$/u, "");
  const response = await fetch(`${base}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "api-key": required(env.QDRANT_API_KEY, "QDRANT_API_KEY"),
    },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(30_000),
  });
  if (!response.ok) throw new Error("qdrant_request_failed");
  const payload = await response.json() as { result?: T; status?: string };
  if (payload.status === "error" || payload.result === undefined) throw new Error("qdrant_request_failed");
  return payload.result;
}

export async function createCleanupPorts(env: CleanupEnv): Promise<{
  ports: CleanupPorts;
  close(): Promise<void>;
}> {
  let mongo: MongoClient | undefined;
  let postgres: Pool | undefined;
  let firebase: FirebaseAuthClient | undefined;
  const getMongo = () => mongo ??= new MongoClient(required(env.MONGODB_URI, "MONGODB_URI"), {
    maxPoolSize: 2,
    minPoolSize: 0,
    serverSelectionTimeoutMS: 15_000,
    connectTimeoutMS: 10_000,
    socketTimeoutMS: 30_000,
  });
  const getPostgres = () => postgres ??= new Pool({
    connectionString: required(env.POSTGRES?.connectionString, "POSTGRES"),
    max: 1,
    connectionTimeoutMillis: 10_000,
    idleTimeoutMillis: 5_000,
  });
  const getFirebase = () => firebase ??= new FirebaseAuthClient(
    required(env.FIREBASE_CREDENTIALS_BASE64, "FIREBASE_CREDENTIALS_BASE64"),
    required(env.FIREBASE_PROJECT_ID, "FIREBASE_PROJECT_ID"),
  );
  const getSessions = () => getMongo().db(required(env.MONGODB_DATABASE, "MONGODB_DATABASE"))
    .collection<{ _id: string; iniciada_em?: Date }>(env.MONGODB_SESSIONS_COLLECTION || "sessoes");
  const getMessages = () => getMongo().db(required(env.MONGODB_DATABASE, "MONGODB_DATABASE"))
    .collection<{ _id: string; data?: Date }>(env.MONGODB_MESSAGES_COLLECTION || "mensagens");
  const collectionName = encodeURIComponent(env.QDRANT_SUMMARIES_COLLECTION || "memoria_resumos");

  const ports: CleanupPorts = {
    accounts: {
      async listFirebaseUids() {
        try {
          const result = await getPostgres().query<{ firebase_uid: string }>(
            "SELECT firebase_uid FROM conta WHERE firebase_uid IS NOT NULL",
          );
          return new Set(result.rows.map((row) => String(row.firebase_uid)));
        } catch {
          throw new Error("postgres_list_uids_failed");
        }
      },
      async firebaseUidExists(uid) {
        try {
          const result = await getPostgres().query<{ exists: boolean }>(
            "SELECT EXISTS (SELECT 1 FROM conta WHERE firebase_uid = $1) AS exists", [uid],
          );
          return Boolean(result.rows[0]?.exists);
        } catch {
          throw new Error("postgres_uid_check_failed");
        }
      },
    },
    firebase: {
      async *listUsers() {
        try {
          yield* getFirebase().listUsers(required(env.FIREBASE_PROJECT_ID, "FIREBASE_PROJECT_ID"));
        } catch (error) {
          const code = error instanceof Error && /^firebase_[a-z_]+$/u.test(error.message)
            ? error.message : "firebase_transport_failed";
          throw new Error(code);
        }
      },
      async deleteUser(uid) {
        try {
          await getFirebase().deleteUser(required(env.FIREBASE_PROJECT_ID, "FIREBASE_PROJECT_ID"), uid);
        } catch {
          throw new Error("firebase_delete_user_failed");
        }
      },
    },
    sessions: {
      async *listExpired(cutoff: Date): AsyncIterable<ExpiredSession> {
        const cursor = mongoDocuments<{ _id: string; iniciada_em?: Date }>(
          getSessions(), expiredFilter("iniciada_em", cutoff), { _id: 1, iniciada_em: 1 },
        );
        for await (const doc of cursor) {
          if (typeof doc._id !== "string" || !(doc.iniciada_em instanceof Date)) throw new Error("invalid_mongo_session");
          yield { id: doc._id, startedAt: doc.iniciada_em };
        }
      },
      async isExpired(id, cutoff) {
        return (await getSessions().findOne(
          { _id: id, ...expiredFilter("iniciada_em", cutoff) }, { projection: { _id: 1 }, maxTimeMS: 30_000 },
        )) !== null;
      },
      async deleteExpired(session, cutoff) {
        const result = await getSessions().deleteOne({
          _id: session.id,
          iniciada_em: { $eq: session.startedAt, $type: "date", $lt: cutoff },
        });
        return result.deletedCount === 1;
      },
    },
    messages: {
      async *listExpired(cutoff: Date): AsyncIterable<ExpiredMessage> {
        const cursor = mongoDocuments<{ _id: string; data?: Date }>(
          getMessages(), expiredFilter("data", cutoff), { _id: 1, data: 1 },
        );
        for await (const doc of cursor) {
          if (typeof doc._id !== "string" || !(doc.data instanceof Date)) throw new Error("invalid_mongo_message");
          yield { id: doc._id, sentAt: doc.data };
        }
      },
      async isExpired(id, cutoff) {
        return (await getMessages().findOne(
          { _id: id, ...expiredFilter("data", cutoff) }, { projection: { _id: 1 }, maxTimeMS: 30_000 },
        )) !== null;
      },
      async deleteExpired(message, cutoff) {
        const result = await getMessages().deleteOne({
          _id: message.id,
          data: { $eq: message.sentAt, $type: "date", $lt: cutoff },
        });
        return result.deletedCount === 1;
      },
    },
    vectors: {
      async countBySessionId(id) {
        const result = await qdrantRequest<{ count: number }>(env,
          `/collections/${collectionName}/points/count`, {
            exact: true,
            filter: { must: [{ key: "session_id", match: { value: id } }] },
          });
        return Number(result.count);
      },
      async deleteBySessionId(id) {
        const count = await this.countBySessionId(id);
        const result = await qdrantRequest<{ status: string }>(env,
          `/collections/${collectionName}/points/delete?wait=true`, {
            filter: { must: [{ key: "session_id", match: { value: id } }] },
          });
        if (result.status !== "completed") throw new Error("qdrant_delete_unconfirmed");
        return count;
      },
    },
  };

  return {
    ports,
    async close() {
      const shutdowns: Promise<unknown>[] = [];
      if (mongo) shutdowns.push(mongo.close());
      if (postgres) shutdowns.push(postgres.end());
      await Promise.allSettled(shutdowns);
    },
  };
}
