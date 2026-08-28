import type { Metadata } from "next";

import { createClient } from "@/lib/supabase/server";
import { TemplateEditor, type Template } from "@/components/admin/TemplateEditor";
import { EmptyState } from "@/components/ui/EmptyState";
import { LayoutTemplate } from "lucide-react";

export const metadata: Metadata = { title: "Lesson format" };

export default async function TemplatesPage() {
  const supabase = await createClient();

  const { data } = await supabase
    .from("lesson_templates")
    .select("*")
    .order("is_default", { ascending: false })
    .limit(1)
    .returns<Template[]>();

  const template = data?.[0];

  if (!template) {
    return (
      <div className="mx-auto max-w-2xl py-10">
        <EmptyState
          icon={LayoutTemplate}
          title="No lesson format yet"
          description="The default template is created by the seed migration. Run 0002_seed_template.sql if it is missing."
        />
      </div>
    );
  }

  return <TemplateEditor template={template} />;
}
