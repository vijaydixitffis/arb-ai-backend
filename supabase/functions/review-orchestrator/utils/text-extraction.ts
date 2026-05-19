// Map MIME types to the extension keys used by extractTextFromArtifact.
export function mimeTypeToExt(mimeType: string): string | undefined {
  const map: Record<string, string> = {
    'application/pdf':   'pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
    'application/msword': 'doc',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx',
    'application/vnd.ms-excel': 'xls',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'pptx',
    'application/vnd.ms-powerpoint': 'ppt',
    'text/plain': 'txt',
  }
  return map[mimeType]
}

export async function extractTextFromArtifact(
  artifactData: Blob,
  fileType: string
): Promise<string> {
  const fileBuffer = await artifactData.arrayBuffer()
  const uint8Array = new Uint8Array(fileBuffer)

  switch (fileType.toLowerCase()) {
    case 'pdf':
      return await extractPDFText(uint8Array)
    case 'docx':
    case 'doc':
      return await extractDocxText(fileBuffer)
    case 'xlsx':
    case 'xls':
      return await extractXlsxText(fileBuffer)
    case 'pptx':
    case 'ppt':
      return await extractPptxText(uint8Array)
    case 'txt':
      return new TextDecoder().decode(uint8Array)
    default:
      throw new Error(`Unsupported file type: ${fileType}`)
  }
}

async function extractPDFText(uint8Array: Uint8Array): Promise<string> {
  // For Deno Edge Functions, we'll use a simple text extraction
  // In production, you might want to use a service or more robust library
  try {
    // Using pdf-parse via CDN
    const pdfParse = await import('https://esm.sh/pdf-parse@1.1.1')
    const data = await pdfParse.default(uint8Array)
    return data.text
  } catch (error) {
    console.error('PDF extraction error:', error)
    throw new Error('Failed to extract text from PDF')
  }
}

async function extractDocxText(arrayBuffer: ArrayBuffer): Promise<string> {
  try {
    // fflate is a pure-JS zip library that works reliably in Deno edge functions.
    // mammoth's { arrayBuffer } input is not recognised in the esm.sh/Deno runtime.
    const { unzipSync } = await import('https://esm.sh/fflate@0.8.2')
    const unzipped = unzipSync(new Uint8Array(arrayBuffer))

    const docXml = unzipped['word/document.xml']
    if (!docXml) throw new Error('word/document.xml not found in DOCX archive')

    const xml = new TextDecoder().decode(docXml)

    // Insert whitespace at paragraph/line-break boundaries before stripping tags
    const text = xml
      .replace(/<w:br[^>]*\/>/g, '\n')
      .replace(/<\/w:p>/g, '\n')
      .replace(/<w:t[^>]*>([^<]*)<\/w:t>/g, '$1')
      .replace(/<[^>]+>/g, '')
      .replace(/[ \t]+/g, ' ')
      .replace(/\n{3,}/g, '\n\n')
      .trim()

    return text
  } catch (error) {
    console.error('DOCX extraction error:', error)
    throw new Error('Failed to extract text from DOCX')
  }
}

async function extractXlsxText(arrayBuffer: ArrayBuffer): Promise<string> {
  try {
    const XLSX = await import('https://esm.sh/xlsx@0.18.5')
    const workbook = XLSX.read(new Uint8Array(arrayBuffer), { type: 'array' })
    const lines: string[] = []
    for (const sheetName of workbook.SheetNames) {
      lines.push(`=== Sheet: ${sheetName} ===`)
      const csv = XLSX.utils.sheet_to_csv(workbook.Sheets[sheetName])
      lines.push(csv)
    }
    return lines.join('\n')
  } catch (error) {
    console.error('XLSX extraction error:', error)
    throw new Error('Failed to extract text from XLSX')
  }
}

async function extractPptxText(uint8Array: Uint8Array): Promise<string> {
  try {
    throw new Error('PPTX extraction not yet implemented. Please convert to PDF or use a document processing service.')
  } catch (error) {
    console.error('PPTX extraction error:', error)
    throw new Error('Failed to extract text from PPTX')
  }
}

// Alternative: Use a document processing service for complex formats
export async function extractTextViaService(
  fileBuffer: ArrayBuffer,
  fileType: string
): Promise<string> {
  // This is a placeholder for using services like:
  // - AWS Textract
  // - Google Document AI
  // - Azure Form Recognizer
  // - Adobe PDF Services
  
  const apiKey = Deno.env.get('DOCUMENT_PROCESSING_API_KEY')
  if (!apiKey) {
    throw new Error('Document processing service API key not configured')
  }
  
  // Implement service-specific logic here
  throw new Error('Document processing service integration not yet implemented')
}
