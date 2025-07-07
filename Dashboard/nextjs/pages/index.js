import { useState } from 'react'

export default function Home() {
  const [prompt, setPrompt] = useState('')
  const [response, setResponse] = useState(null)
  const [clarify, setClarify] = useState('')
  const [clarifyAnswer, setClarifyAnswer] = useState('')
  const [audioUrl, setAudioUrl] = useState('')
  const sessionId = 'default'

  const handleTeach = async () => {
    const formData = new FormData()
    formData.append('user_prompt', prompt)
    formData.append('session_id', sessionId)
    const res = await fetch('http://127.0.0.1:8000/teach', {
      method: 'POST',
      body: formData
    })
    const data = await res.json()
    setResponse(data)

    const text = Object.values(data.engaged_lessons || data.lessons || {}).join('\n')
    if (text) {
      const ttsForm = new FormData()
      ttsForm.append('text', text)
      const ttsRes = await fetch('http://127.0.0.1:8000/tts', {
        method: 'POST',
        body: ttsForm
      })
      const blob = await ttsRes.blob()
      setAudioUrl(URL.createObjectURL(blob))
    }
  }

  const handleClarify = async () => {
    if (!clarify || !response) return
    const topic = Object.keys(response.engaged_lessons || response.lessons || {})[0]
    const formData = new FormData()
    formData.append('user_question', clarify)
    formData.append('topic', topic)
    formData.append('session_id', sessionId)
    const res = await fetch('http://127.0.0.1:8000/clarify', {
      method: 'POST',
      body: formData
    })
    const data = await res.json()
    setClarifyAnswer(data.answer)
  }

  return (
    <div style={{padding: '40px', fontFamily: 'Arial, sans-serif'}}>
      <h1>AI Teacher Dashboard</h1>
      <input
        value={prompt}
        onChange={e => setPrompt(e.target.value)}
        placeholder="Ask a question"
        style={{width: '60%', padding: '8px'}}
      />
      <button onClick={handleTeach} style={{marginLeft: '12px', padding: '8px 16px'}}>
        Chat with Agent
      </button>
      {response && (
        <div style={{marginTop: '30px'}}>
          <h2>Response</h2>
          <pre style={{background: '#f6f6fa', padding: '10px'}}>{JSON.stringify(response, null, 2)}</pre>
          {audioUrl && (
            <audio controls src={audioUrl} style={{marginTop: '10px'}} />
          )}
          <div style={{marginTop: '20px'}}>
            <input
              value={clarify}
              onChange={e => setClarify(e.target.value)}
              placeholder="Follow-up question"
              style={{width: '60%', padding: '8px'}}
            />
            <button onClick={handleClarify} style={{marginLeft: '12px', padding: '8px 16px'}}>
              Clarify
            </button>
            {clarifyAnswer && (
              <p style={{marginTop: '10px'}}>{clarifyAnswer}</p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
