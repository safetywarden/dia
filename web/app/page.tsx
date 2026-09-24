import { requireUser } from "@/lib/session";
import Dashboard from "./dashboard";

export default async function Home() {
  await requireUser();
  return <Dashboard />;
}
