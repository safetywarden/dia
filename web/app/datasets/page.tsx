import { requireUser } from "@/lib/session";
import Datasets from "./datasets";

export default async function Page() {
  await requireUser();
  return <Datasets />;
}
