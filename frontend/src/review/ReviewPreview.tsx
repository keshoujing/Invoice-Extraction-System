import { useEffect, useState } from "react";
import { fileUrl } from "../api";
import { isImage } from "../lib/invoice";
import { Card, CardBody, CardHeader } from "../ui/Card";
import { EmptyState } from "../ui/EmptyState";
import type { Invoice } from "../types";

type ReviewPreviewProps = {
  invoice: Invoice | null;
};

const PDF_PREVIEW_ZOOM = 77;
const PDF_VIEWER_EDGE_TRIM = 16;

function PreviewSkeleton() {
  return (
    <div className="absolute inset-4 overflow-hidden rounded-soft bg-ink-300/10">
      <div className="h-full w-1/2 animate-pulse bg-gradient-to-r from-transparent via-white/70 to-transparent" />
    </div>
  );
}

export function ReviewPreview({ invoice }: ReviewPreviewProps) {
  const [loading, setLoading] = useState(false);
  const previewUrl = invoice ? fileUrl(invoice.id) : "";

  useEffect(() => {
    setLoading(Boolean(invoice));
  }, [invoice?.id]);

  return (
    <Card className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden shadow-cardH">
      <CardHeader
        title={invoice?.original_filename || "Select an invoice"}
        description={invoice ? undefined : "PDF preview appears here"}
        className="px-4 py-2.5"
      />
      <CardBody className={`relative min-h-0 flex-1 overflow-hidden bg-ink-300/5 ${invoice ? "p-0" : "p-3"}`}>
        {!invoice ? (
          <div className="grid h-full min-h-0 place-items-center">
            <EmptyState title="No Preview" description="Select a recognition result on the left to view the original file." />
          </div>
        ) : (
          <>
            {loading ? <PreviewSkeleton /> : null}
            {isImage(invoice) ? (
              <img
                src={previewUrl}
                alt={invoice.original_filename}
                onLoad={() => setLoading(false)}
                onError={() => setLoading(false)}
                className="mx-auto h-full min-h-0 w-full object-contain"
              />
            ) : (
              <iframe
                src={`${previewUrl}#zoom=${PDF_PREVIEW_ZOOM}&toolbar=1`}
                title={invoice.original_filename}
                onLoad={() => setLoading(false)}
                className="absolute border-0 bg-white"
                style={{
                  inset: -PDF_VIEWER_EDGE_TRIM,
                  height: `calc(100% + ${PDF_VIEWER_EDGE_TRIM * 2}px)`,
                  width: `calc(100% + ${PDF_VIEWER_EDGE_TRIM * 2}px)`
                }}
              />
            )}
          </>
        )}
      </CardBody>
    </Card>
  );
}
