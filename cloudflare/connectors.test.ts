import assert from "node:assert/strict";
import { test } from "node:test";
import { MongoClient, ObjectId } from "mongodb";
import { createCleanupPorts, type CleanupEnv } from "./connectors.ts";
import { runCleanup } from "./cleanup.ts";

for (const id of ["507f1f77bcf86cd799439011", new ObjectId("507f1f77bcf86cd799439011")]) {
  for (const dryRun of [false, true]) {
    test(`preserva o tipo ${typeof id} da mensagem no expurgo; dry_run=${dryRun}`, async (t) => {
      const sentAt = new Date("2020-01-01T00:00:00Z");
      const cutoff = new Date("2024-10-21T00:00:00Z");
      const reads: Array<Record<string, unknown>> = [];
      const deletes: Array<Record<string, unknown>> = [];
      const collection = {
        find() {
          return { sort() { return { async *[Symbol.asyncIterator]() { yield { _id: id, data: sentAt }; } }; } };
        },
        async findOne(filter: Record<string, unknown>) { reads.push(filter); return { _id: id }; },
        async deleteOne(filter: Record<string, unknown>) { deletes.push(filter); return { deletedCount: 1 }; },
      };
      t.mock.method(MongoClient.prototype, "db", () => ({ collection: () => collection }) as never);
      t.mock.method(MongoClient.prototype, "close", async () => {});
      const runtime = await createCleanupPorts({ MONGODB_URI: "mongodb://localhost:27017",
        MONGODB_DATABASE: "test" } as CleanupEnv);
      try {
        const summary = await runCleanup("old-conversations", runtime.ports, dryRun,
          new Date("2026-10-21T00:00:00Z"));
        assert.equal(summary.candidates, 1);
        assert.equal(summary.removed, dryRun ? 0 : 1);
        assert.strictEqual(reads[0]._id, id);
        assert.deepEqual(reads[0].data, { $type: "date", $lt: cutoff });
        if (dryRun) assert.equal(deletes.length, 0);
        else {
          assert.strictEqual(deletes[0]._id, id);
          assert.deepEqual(deletes[0].data, { $eq: sentAt, $type: "date", $lt: cutoff });
        }
      } finally { await runtime.close(); }
    });
  }
}
