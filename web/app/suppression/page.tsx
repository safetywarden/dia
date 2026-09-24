import { requireUser } from "@/lib/session";
import SuppressionList from "./list";

export default async function Page() {
  await requireUser();
  return <SuppressionList />;
}
