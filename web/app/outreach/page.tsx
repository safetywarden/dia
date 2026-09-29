import { requireUser } from "@/lib/session";
import OutreachList from "./outreach-list";

export default async function Page() {
  await requireUser();
  return <OutreachList />;
}
