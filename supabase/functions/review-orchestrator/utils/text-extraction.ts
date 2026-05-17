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
    // Using mammoth via CDN for DOCX extraction
    const mammoth = await import('https://esm.sh/mammoth@1.6.0')
    const result = await mammoth.extractRawText({ arrayBuffer })
    return result.value
  } catch (error) {
    console.error('DOCX extraction error:', error)
    throw new Error('Failed to extract text from DOCX')
  }
}

async function extractPptxText(uint8Array: Uint8Array): Promise<string> {
  try {
    // PPTX extraction is more complex in Deno
    // For now, we'll use a basic approach or recommend using a service
    // This is a placeholder - in production, consider using a dedicated service
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
