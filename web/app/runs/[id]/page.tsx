import { requireUser } from "@/lib/session";
import RunView from "./run-view";

export default async function RunPage({ params }: { params: Promise<{ id: string }> }) {
  await requireUser();
  const { id } = await params;
  return <RunView id={Number(id)} />;
}
