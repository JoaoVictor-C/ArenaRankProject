import { PrismaClient } from "@prisma/client";

/**
 * PrismaClient singleton (spec §6).
 *
 * In dev, hot-reload can otherwise spawn many clients and exhaust the
 * connection pool, so we cache the instance on globalThis.
 */
const globalForPrisma = globalThis as unknown as {
  prisma: PrismaClient | undefined;
};

export const prisma: PrismaClient =
  globalForPrisma.prisma ??
  new PrismaClient({
    log: process.env.NODE_ENV === "development" ? ["query", "warn", "error"] : ["warn", "error"],
  });

if (process.env.NODE_ENV !== "production") {
  globalForPrisma.prisma = prisma;
}

/** Graceful shutdown — disconnect the pool on process exit. */
export async function disconnect(): Promise<void> {
  await prisma.$disconnect();
}

export { PrismaClient };
export * from "@prisma/client";
