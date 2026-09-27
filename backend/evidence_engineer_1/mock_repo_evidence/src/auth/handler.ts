export function authenticate(req, res) {
    const token = req.headers.authorization;
    if (!token) throw new Error("Missing token");
    // LINE 42 is here
    const user = verify(token);
    return user;
}