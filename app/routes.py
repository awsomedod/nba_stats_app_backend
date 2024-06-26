import jwt
import datetime
from flask import request, jsonify, g
from jwt import ExpiredSignatureError, DecodeError, InvalidTokenError
from .models import db, User, Player, Team, User_Favorite_Players, User_Favorite_Teams
from .external import get_player_all_season_average
import base64
from . import create_app

app = create_app()

def token_required(f):
    def decorator(*args, **kwargs):
        token = None

        if 'Authorization' in request.headers:
            token = request.headers['Authorization'].split(" ")[1]

        if not token:
            return jsonify({'message': 'Token is missing!'}), 401

        try:
            # Decode the token
            data = jwt.decode(token, app.config['JWT_SECRET_KEY'], algorithms=["HS256"])
            # Find the user, assuming user_id is in the token
            current_user = User.query.get(data['user_id'])
            if not current_user:
                return jsonify({'message': 'User not found'}), 404
            g.user = current_user
        except ExpiredSignatureError:
            # Specifically catch the expired token
            return jsonify({'message': 'Token has expired'}), 401
        except (DecodeError, InvalidTokenError):
            # Catch any other token decoding issues
            return jsonify({'message': 'Token is invalid'}), 401
        except Exception as e:
            # General exception catch
            return jsonify({'message': str(e)}), 500

        return f(*args, **kwargs)
    decorator.__name__ = f.__name__
    return decorator

@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')

    if not username or not email or not password:
        return jsonify({'error': 'Missing data'}), 400

    if User.query.filter_by(username=username).first():
        return jsonify({'error': 'Username already exists'}), 409

    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'Email already registered'}), 409

    user = User(username=username, email=email)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    return jsonify({'message': 'User registered successfully'}), 201

@app.route('/login', methods=['POST'])
def login():
    auth = request.authorization

    if not auth or not auth.username or not auth.password:
        return jsonify({'error': 'Missing username or password'}), 400
    
    username = auth.username
    password = auth.password

    user = User.query.filter_by(username=username).first()
    if user and user.check_password(password):
        token = jwt.encode({
            'user_id': user.id,
            'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24)
        }, app.config['JWT_SECRET_KEY'], algorithm='HS256')
        return jsonify({'user_id': user.id,
                        'token': token}), 200

    return jsonify({'error': 'Invalid username or password'}), 401

def player_to_dict(player):
    if player.picture_data:
        picture_data = base64.b64encode(player.picture_data).decode('utf-8')
    else:
        picture_data = None
    return {
        'player_id': player.id,
        'player_name': player.name,
        'picture': picture_data
    }

def team_to_dict(team):
    players_info = []
    for stats in team.players:
        player = Player.query.get(stats.player_id)
        if player.picture_data:
            picture_data = base64.b64encode(player.picture_data).decode('utf-8')
        else:
            picture_data = None
        players_info.append({'player_id': player.id, 'player_name': player.name, 'picture': picture_data})
    if team.picture_data:
        team_picture_data = base64.b64encode(team.picture_data).decode('utf-8')
    else:
        team_picture_data = None
    
    return {
        'team_id': team.id,
        'team_name': team.team_name,
        'picture': team_picture_data,
        'players': players_info
    }

@app.route('/users/<int:id>', methods=['GET'])
@token_required
def get_user(id):
    if g.user.id != id:
        return jsonify({'error': 'Unauthorized access'}), 403
    
	# Convert favorite players and teams to lists of dictionaries
    favorite_players = [player_to_dict(player) for player in g.user.favorite_players]
    favorite_teams = [team_to_dict(team) for team in g.user.favorite_teams]

    return jsonify({
        'username': g.user.username,
        'email': g.user.email,
        'favorite_players': favorite_players,
        'favorite_teams': favorite_teams
        # include other fields if necessary
    }), 200

@app.route('/users/<int:id>', methods=['PUT'])
@token_required
def update_user(id):
    if g.user.id != id:
        return jsonify({'error': 'Unauthorized access'}), 403
    data = request.get_json()
    g.user.email = data.get('email', g.user.email)
    # update other fields
    db.session.commit()
    return jsonify({'message': 'Profile updated successfully'}), 200

@app.route('/users/<int:id>', methods=['DELETE'])
@token_required
def delete_user(id):
    if g.user.id != id:
        return jsonify({'error': 'Unauthorized access'}), 403
    db.session.delete(g.user)
    db.session.commit()
    return jsonify({'message': 'User deleted successfully'}), 200


@app.route('/players/<int:player_id>', methods=['GET'])
def get_player(player_id):
    # Check if the player exists in the database
    player = Player.query.get(player_id)
    if not player:
        return jsonify({'message': 'Player does not exist'}), 404
    stats = get_player_all_season_average(player)


    # Retrieve and encode the picture data if it exists
    if player.picture_data:
        picture_data = base64.b64encode(player.picture_data).decode('utf-8')
    else:
        picture_data = None

    return jsonify({'player':player_to_dict(player), 'picture': picture_data, 'stats':stats}, 200)


@app.route('/players/search', methods=['GET'])
def search_players():
    # Retrieve the name query parameter from the URL
    name_query = request.args.get('name')
    if not name_query:
        return jsonify({'message': 'No search query provided'}), 400

    # Search for players whose name contains the query, case-insensitive
    players = Player.query.filter(Player.name.ilike(f'%{name_query}%')).all()
    if not players:
        return jsonify({'message': 'No players found matching the search criteria'}), 404

    # Convert the list of player objects to a list of dictionaries
    players_list = []
    for player in players:
        if player.picture_data:
            picture_data = base64.b64encode(player.picture_data).decode('utf-8')
        else:
            picture_data = None
        players_list.append({'id': player.id, 'name': player.name, 'picture': picture_data})
    return jsonify({'players': players_list}), 200

@app.route('/teams/search', methods=['GET'])
def search_teams():
    # Retrieve the name query parameter from the URL
    name_query = request.args.get('name')
    if not name_query:
        return jsonify({'message': 'No search query provided'}), 400

    # Search for players whose name contains the query, case-insensitive
    teams = Team.query.filter(Team.team_name.ilike(f'%{name_query}%')).all()
    if not teams:
        return jsonify({'message': 'No teams found matching the search criteria'}), 404

    # Convert the list of player objects to a list of dictionaries
    team_list = []
    for team in teams:
        if team.picture_data:
            team_picture_data = base64.b64encode(team.picture_data).decode('utf-8')
        else:
            team_picture_data = None
        team_list.append({'id': team.id, 'name': team.team_name, 'picture': team_picture_data})
    return jsonify({'teams': team_list}), 200

@app.route('/teams/<int:team_id>', methods=['GET'])
def get_team(team_id):
    # Check if the team exists in the database
    team = Team.query.get(team_id)
    if not team:
        return jsonify({'message': 'Team does not exist'}), 404
    
    # Retrieve and encode the picture data if it exists
    if team.picture_data:
        team_picture_data = base64.b64encode(team.picture_data).decode('utf-8')
    else:
        team_picture_data = None
    return jsonify({'team':team_to_dict(team), 'picture': team_picture_data}, 200)

@app.route('/users/<int:userId>/favorites/players', methods=['POST'])
@token_required
def add_favorite_player(userId):
    if g.user.id != userId:
        return jsonify({'error': 'Unauthorized access'}), 403

    player_id = request.get_json().get('playerId')
    if not player_id:
        return jsonify({'error': 'Player ID is required'}), 400

    user = User.query.get(userId)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    # Check if the player exists in the database
    player = Player.query.get(player_id)
    if not player:
        return jsonify({'message': 'Player does not exist'}), 404

    # Check if the player is already in the user's favorites
    if player in user.favorite_players:
        return jsonify({'message': 'Player is already in favorites'}), 409

    # Add player to user's favorites
    user.favorite_players.append(player)
    db.session.commit()

    return jsonify({'message': 'Player added to favorites'}), 201


@app.route('/users/<int:userId>/favorites/players', methods=['DELETE'])
@token_required
def remove_favorite_player(userId):
    if g.user.id != userId:
        return jsonify({'error': 'Unauthorized access'}), 403

    player_id = request.get_json().get('playerId')
    if not player_id:
        return jsonify({'error': 'Player ID is required'}), 400

    user = User.query.get(userId)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    # Check if the player is in the user's favorites
    player = Player.query.get(player_id)
    if not player:
        return jsonify({'message': 'Player does not exist'}), 404

    if player not in user.favorite_players:
        return jsonify({'message': 'Player is not in favorites'}), 404

    # Remove the player from user's favorites
    user.favorite_players.remove(player)
    db.session.commit()

    return jsonify({'message': 'Player removed from favorites'}), 200

@app.route('/users/<int:userId>/favorites/teams', methods=['POST'])
@token_required
def add_favorite_team(userId):
    if g.user.id != userId:
        return jsonify({'error': 'Unauthorized access'}), 403

    team_id = request.get_json().get('teamId')
    if not team_id:
        return jsonify({'error': 'Team ID is required'}), 400
    
    user = User.query.get(userId)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    # Check if the Team exists in the database
    team = Team.query.get(team_id)
    if not team:
        return jsonify({'message': 'Team does not exist'}), 404

    # Check if the player is already in the user's favorites
    if team in user.favorite_teams:
        return jsonify({'message': 'Team is already in favorites'}), 409

    # Add player to user's favorites
    user.favorite_teams.append(team)
    db.session.commit()

    return jsonify({'message': 'Team added to favorites'}), 201

@app.route('/users/<int:userId>/favorites/teams', methods=['DELETE'])
@token_required
def remove_favorite_team(userId):
    if g.user.id != userId:
        return jsonify({'error': 'Unauthorized access'}), 403

    team_id = request.get_json().get('teamId')
    if not team_id:
        return jsonify({'error': 'Team ID is required'}), 400

    user = User.query.get(userId)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    # Check if the team is in the user's favorites
    team = Team.query.get(team_id)
    if not team:
        return jsonify({'message': 'Team does not exist'}), 404

    if team not in user.favorite_teams:
        return jsonify({'message': 'Team is not in favorites'}), 404

    # Remove the team from user's favorites
    user.favorite_teams.remove(team)
    db.session.commit()

    return jsonify({'message': 'Team removed from favorites'}), 200

@app.route('/top-players', methods=['GET'])
def get_top_players():
    # Query to get the top 5 players with the most fans
    top_players = db.session.query(
        Player.id, Player.name, Player.picture_data, db.func.count(User_Favorite_Players.user_id).label('fan_count')
    ).join(User_Favorite_Players).group_by(Player.id, Player.name, Player.picture_data).order_by(db.desc('fan_count')).limit(5).all()

    result = []

    for player in top_players:
        if player.picture_data:
            picture_data = base64.b64encode(player.picture_data).decode('utf-8')
        else:
            picture_data = None
        result.append({'id': player.id, 'name': player.name, 'fan_count': player.fan_count, 'picture': picture_data})
    
    return jsonify(result)

@app.route('/top-teams', methods=['GET'])
def get_top_teams():
    # Query to get the top 5 teams with the most fans
    top_teams = db.session.query(
        Team.id, Team.team_name, Team.picture_data, db.func.count(User_Favorite_Teams.user_id).label('fan_count')
    ).join(User_Favorite_Teams).group_by(Team.id, Team.team_name, Team.picture_data).order_by(db.desc('fan_count')).limit(5).all()
    
    result = []
    for team in top_teams:
        if team.picture_data:
            team_picture_data = base64.b64encode(team.picture_data).decode('utf-8')
        else:
            team_picture_data = None
        result.append({'id': team.id, 'name': team.team_name, 'fan_count': team.fan_count, 'picture': team_picture_data})

    return jsonify(result)

@app.route('/')
def home():
    return "hey"
